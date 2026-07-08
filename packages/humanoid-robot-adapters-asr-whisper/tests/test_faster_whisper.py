"""Tests for FasterWhisperAsr with an injected fake model — no runtime deps."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from humanoid_robot.adapters.asr_whisper import (
    FasterWhisperAsr,
    FasterWhisperConfig,
    WhisperRuntimeNotAvailableError,
)
from humanoid_robot.domain.voice import AudioFormat, Language
from humanoid_robot.ports.robot import AudioFrame

_G1_FORMAT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


@dataclass(slots=True)
class _FakeSegment:
    text: str


@dataclass(slots=True)
class _FakeInfo:
    language: str = "ru"
    language_probability: float = 0.98


@dataclass(slots=True)
class _FakeModel:
    scripted_text: str
    transcribed_calls: list[bytes] = field(default_factory=list)

    def transcribe(self, audio: list[float], **_: Any) -> tuple[list[_FakeSegment], _FakeInfo]:
        # Snapshot payload length for later assertions.
        self.transcribed_calls.append(bytes(len(audio) * 2))
        return [_FakeSegment(text=self.scripted_text)], _FakeInfo()


def _make_loader(scripted: str = "Привет робот") -> Any:
    def loader(_config: FasterWhisperConfig) -> _FakeModel:
        return _FakeModel(scripted_text=scripted)

    return loader


def _frame(size: int) -> AudioFrame:
    return AudioFrame(pcm=b"\x00\x00" * size, format=_G1_FORMAT, monotonic_ns=0)


class TestFasterWhisperAsrBatch:
    async def test_missing_runtime_raises(self) -> None:
        asr = FasterWhisperAsr()  # no loader, no faster_whisper installed
        with pytest.raises(WhisperRuntimeNotAvailableError):
            await asr.transcribe_batch(b"\x00" * 32, sample_rate_hz=16_000)

    async def test_batch_returns_transcription(self) -> None:
        asr = FasterWhisperAsr(loader=_make_loader("Привет"))
        result = await asr.transcribe_batch(b"\x00\x00" * 8_000, sample_rate_hz=16_000)
        assert result.text == "Привет"
        assert result.language == Language.RU
        assert 0.0 < result.confidence <= 1.0

    async def test_rejects_wrong_sample_rate(self) -> None:
        asr = FasterWhisperAsr(loader=_make_loader())
        with pytest.raises(ValueError, match="Hz"):
            await asr.transcribe_batch(b"\x00\x00" * 8_000, sample_rate_hz=48_000)


class TestFasterWhisperAsrStreaming:
    async def _feed(self, frames: list[AudioFrame]) -> AsyncIterator[AudioFrame]:
        for f in frames:
            yield f

    async def test_streaming_emits_partial_then_final(self) -> None:
        # 300 ms partial_interval @ 16 kHz mono PCM16 = 9600 bytes.
        # Push 3 frames of 12 000 samples (24 000 bytes each) = 96 ms each? No,
        # 12 000 samples at 16 kHz = 750 ms. So one frame already crosses the
        # partial threshold.
        asr = FasterWhisperAsr(loader=_make_loader("hello"))
        frames = [_frame(12_000), _frame(12_000)]
        chunks = [chunk async for chunk in asr.transcribe_stream(self._feed(frames))]
        assert chunks[-1].is_final
        # At least one partial should have fired before the final.
        assert any(not c.is_final for c in chunks)

    async def test_stream_rejects_mismatched_frame_rate(self) -> None:
        asr = FasterWhisperAsr(loader=_make_loader())
        bad_format = AudioFormat(sample_rate_hz=48_000, channels=1, sample_width_bytes=2)
        bad_frame = AudioFrame(pcm=b"\x00" * 96_000, format=bad_format, monotonic_ns=0)

        async def gen() -> AsyncIterator[AudioFrame]:
            yield bad_frame

        with pytest.raises(ValueError, match="sample_rate_hz"):
            async for _ in asr.transcribe_stream(gen()):
                pass
