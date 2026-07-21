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
import time
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
    LlmRejected,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
    VoiceInterrupt,
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
# Hard ceiling on one synth+play chunk. A wedged piper/vendor call must not
# block the answer queue forever — drop the chunk and move on (self-healing).
_SPEAK_TIMEOUT_S = 30.0
# If the speaking flag shows no progress this long, treat the speaker as idle
# so the mic can't stay deaf behind a stuck utterance.
_SPEAKING_STALL_S = 35.0
# A stream whose generator crashed may never send its final answer; close the
# worker after this long without any new event so the stream can't leak.
_STREAM_IDLE_TIMEOUT_S = 90.0
# How long a finished session keeps swallowing its straggler token events.
_CLOSED_SESSION_TTL_S = 60.0

_LOG = get_logger("cortex-voice.tts")


@dataclass(slots=True)
class _TokenStream:
    """Accumulated state of one in-flight streamed answer.

    Token and final-answer events arrive on SEPARATE bus subscriptions whose
    callbacks run concurrently — with a fast (cloud) model the final answer
    overtakes still-queued tokens, and naive handling loses the last
    sentence(s). Handlers therefore only ENQUEUE here; a per-stream worker
    consumes strictly in arrival order and closes on the final item.
    """

    utterance_id: UtteranceId
    buffer: str = ""
    # Exact concatenation of every delta the worker consumed — compared
    # against the final answer text to speak whatever tokens never made it
    # through the bus before the final event.
    received: str = ""
    duration_ms: int = 0
    # ("token", delta, language) | ("final", full_answer_text, language)
    queue: asyncio.Queue[tuple[str, str, Language]] = field(default_factory=asyncio.Queue)
    worker: asyncio.Task[None] | None = None


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
    _last_progress: float = field(default=0.0)
    # One robot, one speaker: concurrent stream workers must not interleave
    # their sentences on the audio output.
    _speak_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Sessions whose stream already closed: token events still in flight on
    # the bus must not reopen a ghost stream (they were already spoken via
    # the final-text reconciliation).
    _recently_closed: dict[str, float] = field(default_factory=dict)

    @property
    def speaking(self) -> bool:
        # Stall failsafe: a wedged utterance must not keep the mic deaf.
        return (
            self._speaking_depth > 0
            and (time.monotonic() - self._last_progress) < _SPEAKING_STALL_S
        )

    async def start(self) -> Subscription:
        """Subscribe to answer/token/rejected/interrupt events — one handle."""
        answer_sub = await self.bus.subscribe(LlmAnswer.subject, self._on_llm_answer)
        token_sub = await self.bus.subscribe(LlmAnswerToken.subject, self._on_token)
        rejected_sub = await self.bus.subscribe(LlmRejected.subject, self._on_rejected)
        interrupt_sub = await self.bus.subscribe(VoiceInterrupt.subject, self._on_interrupt)
        return _MultiSub([answer_sub, token_sub, rejected_sub, interrupt_sub])

    async def _on_interrupt(self, event: BaseEvent) -> None:
        """UI stop button: cut the speech off (voice barge-in is disabled by
        the half-duplex mic, so the bus event is the interrupt path)."""
        if isinstance(event, VoiceInterrupt):
            await self.interrupt()

    async def _on_rejected(self, event: BaseEvent) -> None:
        """A rejected answer still has to CLOSE its token stream — otherwise the
        speaking flag leaks and the mic stays deaf."""
        if not isinstance(event, LlmRejected):
            return
        stream = self._streams.get(event.session_id)
        if stream is not None:
            self._muted.add(event.session_id)  # drop whatever is still queued
            stream.queue.put_nowait(("final", "", Language.RU))
        else:
            self._muted.discard(event.session_id)

    async def interrupt(self) -> None:
        """Barge-in: the user started talking — stop speaking NOW and mute the
        in-flight answers so their remaining sentences aren't spoken. Their
        workers keep draining silently and close on the final event."""
        task = self._current
        if task is not None and not task.done():
            task.cancel()
        for session_id in self._streams:
            self._muted.add(session_id)
        # Muted workers skip playback, so the flag flips immediately.
        self._speaking_depth = 0
        with contextlib.suppress(Exception):
            await self.audio_out.stop()

    def _wants(self, session_id: str) -> bool:
        return self.speak_all or session_id == self.session_id

    def _is_recently_closed(self, session_id: str) -> bool:
        now = time.monotonic()
        for sid, closed_at in list(self._recently_closed.items()):
            if now - closed_at > _CLOSED_SESSION_TTL_S:
                del self._recently_closed[sid]
        return session_id in self._recently_closed

    async def _speak_serialized(self, text: str, language: Language) -> int:
        async with self._speak_lock:
            return await self._speak_cancellable(text, language)

    async def _speak_cancellable(self, text: str, language: Language) -> int:
        """Speak one chunk in a task `interrupt()` can cancel, with a hard
        timeout so a wedged synth/vendor call can't freeze the answer queue;
        returns ms spoken (0 when interrupted/timed out)."""
        self._current = asyncio.create_task(self._speak(text, language))
        try:
            spoken_ms = await asyncio.wait_for(self._current, timeout=_SPEAK_TIMEOUT_S)
        except TimeoutError:
            _LOG.error("tts.speak_timeout", text=text[:60])
            with contextlib.suppress(Exception):
                await self.audio_out.stop()
            return 0
        except asyncio.CancelledError:
            return 0
        else:
            self._last_progress = time.monotonic()
            return spoken_ms
        finally:
            self._current = None

    async def _ensure_stream(self, session_id: str) -> _TokenStream:
        stream = self._streams.get(session_id)
        if stream is not None:
            return stream
        if len(self._streams) >= _MAX_TRACKED_STREAMS:
            # Ask the oldest worker to close; it pops itself from the dict.
            evicted = next(iter(self._streams.values()))
            evicted.queue.put_nowait(("final", "", Language.RU))
        stream = _TokenStream(utterance_id=new_utterance_id())
        self._streams[session_id] = stream
        await self._publish_started(stream.utterance_id)
        stream.worker = asyncio.create_task(
            self._stream_worker(session_id, stream), name=f"tts-stream[{session_id}]"
        )
        return stream

    async def _stream_worker(self, session_id: str, stream: _TokenStream) -> None:
        """Consume one stream's events strictly in arrival order.

        The final answer only closes the stream AFTER every queued token has
        been spoken — a fast generator can no longer overtake its own tail.
        """
        try:
            while True:
                try:
                    kind, text, language = await asyncio.wait_for(
                        stream.queue.get(), timeout=_STREAM_IDLE_TIMEOUT_S
                    )
                except TimeoutError:
                    _LOG.warning("tts.stream_idle_closed", session_id=session_id)
                    break
                if session_id in self._muted:
                    if kind == "final":
                        break
                    continue
                if kind == "token":
                    stream.received += text
                    stream.buffer += text
                    await self._speak_complete_sentences(session_id, stream, language)
                    continue
                await self._flush_tail(session_id, stream, text, language)
                break
        except Exception:
            _LOG.exception("tts.stream_worker_crashed", session_id=session_id)
        finally:
            self._streams.pop(session_id, None)
            self._muted.discard(session_id)
            self._recently_closed[session_id] = time.monotonic()
            await self._publish_finished(stream.utterance_id, stream.duration_ms)

    async def _speak_complete_sentences(
        self, session_id: str, stream: _TokenStream, language: Language
    ) -> None:
        while True:
            match = _COMPLETE_SENTENCE_RE.match(stream.buffer)
            if match is None:
                return
            sentence, stream.buffer = match.group(1).strip(), match.group(2)
            if sentence:
                stream.duration_ms += await self._speak_serialized(sentence, language)
            if session_id in self._muted:
                return

    async def _flush_tail(
        self, session_id: str, stream: _TokenStream, final_text: str, language: Language
    ) -> None:
        """Speak everything the answer still owes at final-answer time.

        The bus gives no cross-subject ordering guarantee, so token events may
        STILL be in flight when the final answer lands. The final text is the
        complete answer — reconcile against what the token path already
        consumed and speak the rest, so nothing is ever swallowed.
        """
        remainder = ""
        if final_text and final_text.startswith(stream.received):
            remainder = final_text[len(stream.received) :]
        pending = (stream.buffer + remainder).strip()
        stream.buffer = ""
        if not pending:
            return
        if not remainder and not _ends_sentence(pending) and stream.duration_ms > 0:
            # No authoritative final text to complete it with (empty final or
            # a mismatch) — an unpunctuated tail is a truncation artifact.
            _LOG.info("tts.drop_truncated_tail", tail=pending[:60])
            return
        for sentence in _split_sentences(pending):
            stream.duration_ms += await self._speak_serialized(sentence, language)
            if session_id in self._muted:
                return

    async def _on_token(self, event: BaseEvent) -> None:
        if not isinstance(event, LlmAnswerToken):
            return
        if not self._wants(event.session_id):
            return
        if event.session_id in self._muted and event.session_id not in self._streams:
            return  # tokens straggling in after an interrupt closed the stream
        if self._is_recently_closed(event.session_id):
            return  # stream already finished; its text was fully spoken
        stream = await self._ensure_stream(event.session_id)
        stream.queue.put_nowait(("token", event.delta_text, Language.RU))

    async def _on_llm_answer(self, event: BaseEvent) -> None:
        if not isinstance(event, LlmAnswer):
            return
        if not self._wants(event.session_id):
            return
        language = self._language_for_event(event)
        stream = self._streams.get(event.session_id)
        if stream is not None:
            stream.queue.put_nowait(("final", event.text, language))
            return
        if event.session_id in self._muted:
            # The user talked over this answer — swallow its final event.
            self._muted.discard(event.session_id)
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
                async with self._speak_lock:
                    while True:
                        frame = await queue.get()
                        if frame is None:
                            break
                        self._current = asyncio.create_task(self._play_frame(frame))
                        try:
                            duration_ms += await asyncio.wait_for(
                                self._current, timeout=_SPEAK_TIMEOUT_S
                            )
                            self._last_progress = time.monotonic()
                        except TimeoutError:
                            _LOG.error("tts.play_timeout")
                            break
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
        self._last_progress = time.monotonic()
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
