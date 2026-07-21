"""TtsSpeaker tests — LlmAnswer → TTS → AudioOut."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from humanoid_robot.domain.knowledge import Citation
from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
)
from humanoid_robot.domain.voice import AudioFormat, Language
from humanoid_robot.events import (
    LlmAnswer,
    LlmAnswerToken,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.ports.ai import TtsRequest
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.testing import InMemoryEventBus
from humanoid_robot.voice import TtsSpeaker

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeTts:
    chunks: list[bytes]

    def synthesize_stream(self, _req: TtsRequest) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            for c in self.chunks:
                yield AudioFrame(pcm=c, format=_FMT, monotonic_ns=0)

        return _gen()

    async def synthesize(self, _req: TtsRequest) -> AudioFrame:
        return AudioFrame(pcm=b"".join(self.chunks), format=_FMT, monotonic_ns=0)


@dataclass(slots=True)
class _FakeAudioOut:
    played: list[bytes] = field(default_factory=list)

    async def play(self, frame: AudioFrame) -> None:
        self.played.append(frame.pcm)

    async def flush(self) -> None:
        return

    async def stop(self) -> None:
        return


def _mk_llm_answer(session_id: str, text: str) -> LlmAnswer:
    return LlmAnswer(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=session_id,  # type: ignore[arg-type]
        text=text,
        citations=(Citation(chunk_id="c1", quote="offline"),),
        confidence=0.9,
    )


class TestTtsSpeaker:
    async def test_llm_answer_triggers_tts_and_playback(self) -> None:
        session_id = new_session_id()
        bus = InMemoryEventBus()
        tts = _FakeTts(chunks=[b"\x00\x01" * 800, b"\x02\x03" * 800])
        audio_out = _FakeAudioOut()
        speaker = TtsSpeaker(tts=tts, audio_out=audio_out, bus=bus, session_id=session_id)
        await speaker.start()
        await bus.publish(_mk_llm_answer(session_id, "Привет"))

        # The speaker synthesizes the whole utterance in one shot (gap-free
        # playback), so the audio arrives as a single joined frame.
        assert audio_out.played == [b"\x00\x01" * 800 + b"\x02\x03" * 800]
        subjects = [type(ev).subject for ev in bus.published]
        assert "tts.synth.started" in subjects
        assert "tts.synth.finished" in subjects

    async def test_ignores_answers_from_other_sessions(self) -> None:
        session_id = new_session_id()
        other = new_session_id()
        bus = InMemoryEventBus()
        tts = _FakeTts(chunks=[b"\x00" * 400])
        audio_out = _FakeAudioOut()
        speaker = TtsSpeaker(tts=tts, audio_out=audio_out, bus=bus, session_id=session_id)
        await speaker.start()
        await bus.publish(_mk_llm_answer(other, "не мне"))

        assert audio_out.played == []
        assert not any(isinstance(ev, TtsSynthesisStarted) for ev in bus.published)
        assert not any(isinstance(ev, TtsSynthesisFinished) for ev in bus.published)

    def test_language_default_when_not_present(self) -> None:
        # LlmAnswer as defined today does not carry a language field; the
        # speaker falls back to Russian.
        speaker = TtsSpeaker(
            tts=_FakeTts(chunks=[]),
            audio_out=_FakeAudioOut(),
            bus=InMemoryEventBus(),
            session_id=new_session_id(),
        )
        event = _mk_llm_answer(speaker.session_id, "x")
        assert speaker._language_for_event(event) == Language.RU


@dataclass(slots=True)
class _RecordingTts:
    """Records the exact texts sent to synthesis."""

    texts: list[str] = field(default_factory=list)

    def synthesize_stream(self, _req: TtsRequest) -> AsyncIterator[AudioFrame]:
        raise NotImplementedError

    async def synthesize(self, req: TtsRequest) -> AudioFrame:
        self.texts.append(req.text)
        return AudioFrame(pcm=b"\x00\x01" * 160, format=_FMT, monotonic_ns=0)


def _mk_token(session_id: str, sequence: int, delta: str) -> LlmAnswerToken:
    return LlmAnswerToken(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=session_id,  # type: ignore[arg-type]
        sequence=sequence,
        delta_text=delta,
    )


class TestStreamedAnswerOrdering:
    async def test_burst_stream_speaks_every_sentence(self) -> None:
        """Cloud models emit all tokens AND the final answer in one burst; the
        final event must not overtake queued tokens (that lost the last
        sentence: the robot audibly stopped before finishing its answer)."""
        session_id = new_session_id()
        bus = InMemoryEventBus()
        tts = _RecordingTts()
        audio_out = _FakeAudioOut()
        speaker = TtsSpeaker(tts=tts, audio_out=audio_out, bus=bus, session_id=session_id)
        await speaker.start()

        text = "Первое предложение. Второе предложение. Третий хвост без пробела."
        words = text.split(" ")
        for i, word in enumerate(words):
            suffix = " " if i < len(words) - 1 else ""
            await bus.publish(_mk_token(session_id, i, word + suffix))
        await bus.publish(_mk_llm_answer(session_id, text))

        # The worker drains asynchronously — wait for the finished event.
        for _ in range(500):
            if any(isinstance(ev, TtsSynthesisFinished) for ev in bus.published):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("stream never finished")

        assert tts.texts == [
            "Первое предложение.",
            "Второе предложение.",
            "Третий хвост без пробела.",
        ]
