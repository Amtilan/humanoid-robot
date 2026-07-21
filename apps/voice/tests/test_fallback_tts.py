"""FallbackTts: cloud-first, Piper when the cloud fails."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from humanoid_robot.domain.voice import AudioFormat, Language
from humanoid_robot.ports import AudioFrame, TtsRequest
from humanoid_robot.voice.fallback_tts import FallbackTts

_FMT = AudioFormat(sample_rate_hz=16_000, channels=1, sample_width_bytes=2)


def _frame(tag: bytes) -> AudioFrame:
    return AudioFrame(pcm=tag, format=_FMT, monotonic_ns=time.monotonic_ns())


class _GoodTts:
    def __init__(self, tag: bytes) -> None:
        self.tag = tag

    async def synthesize(self, request: TtsRequest) -> AudioFrame:
        return _frame(self.tag)

    async def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]:
        yield _frame(self.tag)


class _BrokenTts:
    async def synthesize(self, request: TtsRequest) -> AudioFrame:
        raise RuntimeError("cloud down")

    async def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]:
        raise RuntimeError("cloud down")
        yield  # pragma: no cover


_REQ = TtsRequest(text="привет", language=Language.RU)


async def test_primary_wins_when_healthy() -> None:
    tts = FallbackTts(_GoodTts(b"cloud"), _GoodTts(b"local"))
    assert (await tts.synthesize(_REQ)).pcm == b"cloud"
    frames = [f async for f in tts.synthesize_stream(_REQ)]
    assert [f.pcm for f in frames] == [b"cloud"]


async def test_fallback_on_primary_failure() -> None:
    tts = FallbackTts(_BrokenTts(), _GoodTts(b"local"))
    assert (await tts.synthesize(_REQ)).pcm == b"local"
    frames = [f async for f in tts.synthesize_stream(_REQ)]
    assert [f.pcm for f in frames] == [b"local"]
