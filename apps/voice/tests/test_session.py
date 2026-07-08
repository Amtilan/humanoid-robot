"""End-to-end VoiceSession tests with in-memory fakes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from humanoid_robot.domain.voice import (
    AudioFormat,
    Language,
    Transcription,
)
from humanoid_robot.events import AsrFinal, SpeechDetected, WakeWordTriggered
from humanoid_robot.ports.ai import AsrStreamChunk
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.ports.voice import VadDecision, WakeWordEvent
from humanoid_robot.testing import InMemoryEventBus
from humanoid_robot.voice import VoiceSession, VoiceSessionConfig

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeVad:
    scripted: list[bool]
    _index: int = 0

    async def decide(self, _frame: AudioFrame) -> VadDecision:
        is_speech = self.scripted[self._index]
        self._index = min(self._index + 1, len(self.scripted) - 1)
        return VadDecision(
            is_speech=is_speech,
            speech_probability=0.9 if is_speech else 0.05,
        )

    async def reset(self) -> None:
        self._index = 0


@dataclass(slots=True)
class _FakeAsr:
    scripted_text: str
    calls: list[bytes] = field(default_factory=list)

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        self.calls.append(pcm)
        return Transcription(text=self.scripted_text, language=Language.RU, confidence=0.95)

    def transcribe_stream(  # pragma: no cover — not exercised here
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        del frames, language_hint
        raise NotImplementedError


def _frame(samples: int) -> AudioFrame:
    return AudioFrame(pcm=b"\x00\x01" * samples, format=_FMT, monotonic_ns=0)


async def _feed(frames: list[AudioFrame]) -> AsyncIterator[AudioFrame]:
    for f in frames:
        yield f


class TestVoiceSession:
    async def test_publishes_speech_detected_and_asr_final(self) -> None:
        # 20 speech frames of 100 ms (1600 samples) = 2 s speech, then
        # 8 silence frames of 100 ms = 800 ms silence — enough hang time.
        script = [True] * 20 + [False] * 8
        vad = _FakeVad(scripted=script)
        asr = _FakeAsr(scripted_text="Привет робот")
        bus = InMemoryEventBus()
        session = VoiceSession(
            vad=vad,
            asr=asr,
            bus=bus,
            config=VoiceSessionConfig(
                language_hint=Language.RU,
                min_speech_ms=100,
                silence_hang_ms=500,
            ),
        )
        frames = [_frame(1600) for _ in range(len(script))]  # 100 ms each
        await session.run(_feed(frames))

        subjects = [type(ev).subject for ev in bus.published]
        assert "speech.vad.detected" in subjects
        assert "asr.final" in subjects

        final = next(ev for ev in bus.published if isinstance(ev, AsrFinal))
        assert final.text == "Привет робот"
        assert final.language == Language.RU
        assert len(asr.calls) == 1

    async def test_short_utterance_dropped_after_silence(self) -> None:
        # 1 speech frame (100 ms) then long silence → below min_speech_ms.
        script = [True] + [False] * 10
        vad = _FakeVad(scripted=script)
        asr = _FakeAsr(scripted_text="…")
        bus = InMemoryEventBus()
        session = VoiceSession(
            vad=vad,
            asr=asr,
            bus=bus,
            config=VoiceSessionConfig(
                min_speech_ms=300,
                silence_hang_ms=400,
            ),
        )
        frames = [_frame(1600) for _ in range(len(script))]
        await session.run(_feed(frames))

        assert not any(isinstance(ev, AsrFinal) for ev in bus.published)
        assert any(isinstance(ev, SpeechDetected) for ev in bus.published)
        assert asr.calls == []


@dataclass(slots=True)
class _FakeWakeWord:
    fire_on_frame_index: int
    _index: int = 0

    async def feed(self, _frame: AudioFrame) -> WakeWordEvent | None:
        self._index += 1
        if self._index == self.fire_on_frame_index:
            return WakeWordEvent(word="hey_robot", score=0.99)
        return None

    def keywords(self) -> tuple[str, ...]:
        return ("hey_robot",)


class TestVoiceSessionWakeWord:
    async def test_wake_word_gates_listening(self) -> None:
        # 5 silent frames before wake-word; wake-word on frame 6; then speech.
        script = [False] * 5 + [False] * 20 + [True] * 15 + [False] * 8
        vad = _FakeVad(scripted=script)
        wake = _FakeWakeWord(fire_on_frame_index=6)
        asr = _FakeAsr(scripted_text="теперь я слушаю")
        bus = InMemoryEventBus()
        session = VoiceSession(
            vad=vad,
            asr=asr,
            bus=bus,
            wake_word=wake,
            config=VoiceSessionConfig(
                require_wake_word=True,
                min_speech_ms=100,
                silence_hang_ms=400,
                wake_word_grace_ms=5000,
            ),
        )
        frames = [_frame(1600) for _ in range(len(script))]
        await session.run(_feed(frames))

        subjects = [type(ev).subject for ev in bus.published]
        assert "speech.wake_word.triggered" in subjects
        assert "asr.final" in subjects

    async def test_wake_word_without_speech_returns_to_idle(self) -> None:
        # Wake-word fires but no speech follows — grace period elapses.
        # Frame 1 = wake, then all silence.
        script = [False] * 40
        vad = _FakeVad(scripted=script)
        wake = _FakeWakeWord(fire_on_frame_index=1)
        asr = _FakeAsr(scripted_text="…")
        bus = InMemoryEventBus()
        session = VoiceSession(
            vad=vad,
            asr=asr,
            bus=bus,
            wake_word=wake,
            config=VoiceSessionConfig(
                require_wake_word=True,
                min_speech_ms=100,
                silence_hang_ms=400,
                wake_word_grace_ms=500,
            ),
        )
        frames = [_frame(1600) for _ in range(len(script))]
        await session.run(_feed(frames))

        subjects = [type(ev).subject for ev in bus.published]
        assert "speech.wake_word.triggered" in subjects
        assert "asr.final" not in subjects
        # Verify the state came back to IDLE.
        from humanoid_robot.voice import VoiceSessionState

        assert session.state == VoiceSessionState.IDLE
        # silence WakeWordTriggered event object exists
        assert any(isinstance(ev, WakeWordTriggered) for ev in bus.published)
