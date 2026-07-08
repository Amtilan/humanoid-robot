"""VoiceRunner end-to-end tests with all-fake ports."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from humanoid_robot.domain.knowledge import Citation
from humanoid_robot.domain.shared import new_correlation_id, new_session_id
from humanoid_robot.domain.voice import AudioFormat, Language, Transcription
from humanoid_robot.events import AsrFinal, LlmAnswer
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.ports.ai import AsrStreamChunk, TtsRequest
from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.ports.voice import VadDecision
from humanoid_robot.testing import InMemoryEventBus
from humanoid_robot.voice import VoiceRunner, VoiceSessionConfig

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


def _frame(samples: int) -> AudioFrame:
    return AudioFrame(pcm=b"\x00\x01" * samples, format=_FMT, monotonic_ns=0)


@dataclass(slots=True)
class _FakeAudioIn:
    scripted: list[AudioFrame]
    _closed: bool = False

    def stream(self) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            for f in self.scripted:
                if self._closed:
                    return
                await asyncio.sleep(0)  # yield to event loop
                yield f

        return _gen()

    async def close(self) -> None:
        self._closed = True


@dataclass(slots=True)
class _FakeAudioOut:
    played: list[bytes] = field(default_factory=list)

    async def play(self, frame: AudioFrame) -> None:
        self.played.append(frame.pcm)

    async def flush(self) -> None:
        return

    async def stop(self) -> None:
        return


@dataclass(slots=True)
class _FakeVad:
    scripted: list[bool]
    _index: int = 0

    async def decide(self, _f: AudioFrame) -> VadDecision:
        is_speech = self.scripted[self._index]
        self._index = min(self._index + 1, len(self.scripted) - 1)
        return VadDecision(is_speech=is_speech, speech_probability=0.9 if is_speech else 0.1)

    async def reset(self) -> None:
        self._index = 0


@dataclass(slots=True)
class _FakeAsr:
    scripted_text: str

    async def transcribe_batch(
        self,
        _pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        del sample_rate_hz, language_hint
        return Transcription(text=self.scripted_text, language=Language.RU, confidence=0.95)

    def transcribe_stream(  # pragma: no cover
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        del frames, language_hint
        raise NotImplementedError


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


class TestVoiceRunner:
    async def test_full_loop_mic_to_asr_and_llm_answer_to_speaker(self) -> None:
        session_id = new_session_id()
        # 20 speech frames + 8 silence frames (100 ms each).
        script = [True] * 20 + [False] * 8
        mic_frames = [_frame(1600) for _ in range(len(script))]

        bus = InMemoryEventBus()
        audio_in = _FakeAudioIn(scripted=mic_frames)
        audio_out = _FakeAudioOut()
        vad = _FakeVad(scripted=script)
        asr = _FakeAsr(scripted_text="Привет робот")
        tts = _FakeTts(chunks=[b"\x00\x01" * 400])

        runner = VoiceRunner(
            audio_in=audio_in,
            audio_out=audio_out,
            vad=vad,
            asr=asr,
            tts=tts,
            bus=bus,
            config=VoiceSessionConfig(min_speech_ms=100, silence_hang_ms=400),
            session_id=session_id,
        )
        run_task = asyncio.create_task(runner.run())

        # Wait until the AsrFinal has been published, then inject an
        # LlmAnswer to close the loop.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if any(isinstance(ev, AsrFinal) for ev in bus.published):
                break

        assert any(isinstance(ev, AsrFinal) for ev in bus.published)

        await bus.publish(
            LlmAnswer(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer="tests",
                ),
                session_id=session_id,
                text="ответ",
                citations=(Citation(chunk_id="c1", quote="offline"),),
                confidence=0.9,
            )
        )

        # Give the TTS speaker a moment to run.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if audio_out.played:
                break

        assert audio_out.played, "audio_out should have received TTS frames"

        runner.request_stop()
        await run_task
