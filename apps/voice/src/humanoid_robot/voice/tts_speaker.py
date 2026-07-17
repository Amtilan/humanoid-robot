"""Output side — turn LLM answers into speech on the robot speaker.

Two paths:

* **Streaming** (Alice-style): consume ``llm.answer.token`` deltas, cut them
  into sentences and synthesize+play each sentence while the model is still
  generating the rest — speech starts after the FIRST sentence. The final
  ``llm.answer`` then only flushes the tail (no re-speaking).
* **Batch**: an ``llm.answer`` with no preceding tokens (grounded QA, the
  /voice/say endpoint) is spoken with a per-sentence producer pipeline.

Kept separate from `VoiceSession` (input side) so each concern owns one state
machine. The two share the same session id via the runner.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field

from humanoid_robot.domain.shared import (
    SessionId,
    UtteranceId,
    new_correlation_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import (
    BaseEvent,
    LlmAnswer,
    LlmAnswerToken,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import (
    AudioFrame,
    AudioOutPort,
    EventBusPort,
    Subscription,
    TtsPort,
    TtsRequest,
)

# Split on sentence-final punctuation, keeping the delimiter with the sentence.
_SENTENCE_RE = re.compile(r".+?(?:[.!?…]+(?:\s|$)|$)", re.DOTALL)
# A COMPLETE sentence during streaming: punctuation followed by whitespace.
# Trailing punctuation without a following space stays buffered (could be
# "3." of "3.5"); the final-answer flush speaks whatever remains.
_COMPLETE_SENTENCE_RE = re.compile(r"^\s*(.*?[.!?…]+)\s+(.*)$", re.DOTALL)
# Don't let half-open token streams accumulate forever if a final answer
# never arrives (crashed generator).
_MAX_TRACKED_STREAMS = 8

_LOG = get_logger("cortex-voice.tts")


@dataclass(slots=True)
class _TokenStream:
    """Accumulated state of one in-flight streamed answer."""

    utterance_id: UtteranceId
    buffer: str = ""
    duration_ms: int = 0


class _MultiSub:
    """Cancels several bus subscriptions as one handle."""

    def __init__(self, subs: list[Subscription]) -> None:
        self._subs = subs

    async def cancel(self) -> None:
        for sub in self._subs:
            await sub.cancel()


@dataclass(slots=True)
class TtsSpeaker:
    """Subscribes to `llm.answer(.token)` events and drives TTS→speaker output."""

    tts: TtsPort
    audio_out: AudioOutPort
    bus: EventBusPort
    session_id: SessionId
    producer: str = "cortex-voice"
    # When true, speak EVERY llm.answer, not just this voice session's — so
    # text chat / browser push-to-talk answers are also spoken aloud. Useful
    # when the robot's own mic can't be used and input comes from the dashboard.
    speak_all: bool = False
    _streams: dict[str, _TokenStream] = field(default_factory=dict)
    # Sessions muted by a barge-in: their remaining tokens/final answer are
    # dropped instead of spoken (the user talked over the robot).
    _muted: set[str] = field(default_factory=set)
    _current: asyncio.Task[int] | None = field(default=None)
    # >0 while an answer is being spoken (start..finished); exposed so the
    # session can apply "interrupt only by name while the robot talks".
    _speaking_depth: int = field(default=0)

    @property
    def speaking(self) -> bool:
        return self._speaking_depth > 0

    async def start(self) -> Subscription:
        """Subscribe to answer + token events — returns one cancel handle."""
        answer_sub = await self.bus.subscribe(LlmAnswer.subject, self._on_llm_answer)
        token_sub = await self.bus.subscribe(LlmAnswerToken.subject, self._on_token)
        return _MultiSub([answer_sub, token_sub])

    async def interrupt(self) -> None:
        """Barge-in: the user started talking — stop speaking NOW and mute the
        in-flight answers so their remaining sentences aren't spoken."""
        task = self._current
        if task is not None and not task.done():
            task.cancel()
        for session_id in self._streams:
            self._muted.add(session_id)
        self._streams.clear()
        # Interrupted streams never reach their _publish_finished — don't let
        # the speaking flag stick.
        self._speaking_depth = 0
        with contextlib.suppress(Exception):
            await self.audio_out.stop()

    def _wants(self, session_id: str) -> bool:
        return self.speak_all or session_id == self.session_id

    async def _speak_cancellable(self, text: str, language: Language) -> int:
        """Speak one chunk in a task `interrupt()` can cancel; returns ms
        spoken (0 when interrupted)."""
        self._current = asyncio.create_task(self._speak(text, language))
        try:
            return await self._current
        except asyncio.CancelledError:
            return 0
        finally:
            self._current = None

    async def _on_token(self, event: BaseEvent) -> None:
        if not isinstance(event, LlmAnswerToken):
            return
        if not self._wants(event.session_id) or event.session_id in self._muted:
            return
        stream = self._streams.get(event.session_id)
        if stream is None:
            if len(self._streams) >= _MAX_TRACKED_STREAMS:
                self._streams.pop(next(iter(self._streams)))
            stream = _TokenStream(utterance_id=new_utterance_id())
            self._streams[event.session_id] = stream
            await self._publish_started(stream.utterance_id)
        stream.buffer += event.delta_text
        # Speak every complete sentence accumulated so far. Handlers run
        # sequentially per subscription, so later tokens queue up behind this
        # playback and the sentences come out in order.
        while True:
            match = _COMPLETE_SENTENCE_RE.match(stream.buffer)
            if match is None:
                break
            sentence, stream.buffer = match.group(1).strip(), match.group(2)
            if sentence:
                stream.duration_ms += await self._speak_cancellable(sentence, Language.RU)
            if event.session_id in self._muted:
                # Interrupted mid-stream — drop the rest.
                return

    async def _on_llm_answer(self, event: BaseEvent) -> None:
        if not isinstance(event, LlmAnswer):
            return
        if event.session_id in self._muted:
            # The user talked over this answer — swallow its final event.
            self._muted.discard(event.session_id)
            return
        if not self._wants(event.session_id):
            return
        language = self._language_for_event(event)
        stream = self._streams.pop(event.session_id, None)
        if stream is not None:
            # Streamed answer: the sentences were already spoken from tokens —
            # just flush whatever tail is still buffered. A tail WITHOUT
            # sentence-final punctuation is a max_tokens truncation artifact;
            # speaking it stops the robot mid-word, so drop it (unless nothing
            # was spoken yet — half an answer beats silence).
            duration_ms = stream.duration_ms
            tail = stream.buffer.strip()
            if tail and (_ends_sentence(tail) or duration_ms == 0):
                duration_ms += await self._speak_cancellable(tail, language)
            elif tail:
                _LOG.info("tts.drop_truncated_tail", tail=tail[:60])
            await self._publish_finished(stream.utterance_id, duration_ms)
            return
        await self._speak_batch(event.text, language)

    async def _speak_batch(self, text: str, language: Language) -> None:
        """Speak a complete answer: per-sentence synth pipeline with a
        one-sentence lead so audio starts after the first sentence yet stays
        gap-free (piper synthesizes faster than realtime)."""
        utterance_id = new_utterance_id()
        await self._publish_started(utterance_id)
        duration_ms = 0
        try:
            sentences = _split_sentences(text)
            # Drop a truncated final fragment (no sentence-final punctuation)
            # when there are complete sentences before it — a max_tokens cut
            # spoken aloud stops the robot mid-word.
            if len(sentences) > 1 and not _ends_sentence(sentences[-1]):
                _LOG.info("tts.drop_truncated_tail", tail=sentences[-1][:60])
                sentences = sentences[:-1]
            if not sentences:
                return
            queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue(maxsize=1)

            async def _produce() -> None:
                for sentence in sentences:
                    frame = await self.tts.synthesize(TtsRequest(text=sentence, language=language))
                    if frame.pcm:
                        await queue.put(frame)
                await queue.put(None)

            producer = asyncio.create_task(_produce())
            try:
                while True:
                    frame = await queue.get()
                    if frame is None:
                        break
                    self._current = asyncio.create_task(self._play_frame(frame))
                    try:
                        duration_ms += await self._current
                    except asyncio.CancelledError:
                        break  # barge-in — stop this answer
                    finally:
                        self._current = None
            finally:
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await producer
        finally:
            await self._publish_finished(utterance_id, duration_ms)

    async def _play_frame(self, frame: AudioFrame) -> int:
        await self.audio_out.play(frame)
        return _frame_ms(frame)

    async def _speak(self, text: str, language: Language) -> int:
        """Synthesize + play one chunk; returns its duration in ms."""
        frame = await self.tts.synthesize(TtsRequest(text=text, language=language))
        if not frame.pcm:
            return 0
        await self.audio_out.play(frame)
        return _frame_ms(frame)

    def _language_for_event(self, event: LlmAnswer) -> Language:
        return getattr(event, "language", Language.RU)

    async def _publish_started(self, utterance_id: UtteranceId) -> None:
        self._speaking_depth += 1
        await self.bus.publish(
            TtsSynthesisStarted(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=self.session_id,
                utterance_id=utterance_id,
            )
        )

    async def _publish_finished(self, utterance_id: UtteranceId, duration_ms: int) -> None:
        self._speaking_depth = max(0, self._speaking_depth - 1)
        await self.bus.publish(
            TtsSynthesisFinished(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.producer,
                ),
                session_id=self.session_id,
                utterance_id=utterance_id,
                duration_ms=duration_ms,
            )
        )


def _frame_ms(frame: object) -> int:
    """Approximate a frame's duration in ms from its PCM + format."""
    pcm: bytes = getattr(frame, "pcm", b"")
    fmt = getattr(frame, "format", None)
    if fmt is None or not pcm:
        return 0
    bytes_per_second = int(fmt.bytes_per_second)
    return len(pcm) * 1000 // bytes_per_second


def _ends_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?…]\s*$", text))


def _split_sentences(text: str) -> list[str]:
    """Split into sentences so the first can be synthesized and spoken while the
    rest are still being synthesized. Falls back to the whole text if there are
    no sentence breaks."""
    parts = [m.group(0).strip() for m in _SENTENCE_RE.finditer(text)]
    return [p for p in parts if p]
