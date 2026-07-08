"""Tests for PiperTts with an injected fake Piper voice."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from humanoid_robot.adapters.tts_piper import (
    PiperConfig,
    PiperRuntimeNotAvailableError,
    PiperTts,
    PiperVoiceNotConfiguredError,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.ports.ai import TtsRequest


@dataclass(slots=True)
class _FakeVoiceConfig:
    sample_rate: int = 22_050


@dataclass(slots=True)
class _FakeVoice:
    scripted_chunks: list[bytes] = field(default_factory=list)
    config: _FakeVoiceConfig = field(default_factory=_FakeVoiceConfig)

    def synthesize_stream_raw(self, _text: str) -> Iterator[bytes]:
        yield from self.scripted_chunks


def _mk_loader(chunks: list[bytes]) -> Any:
    def loader(_path: str) -> _FakeVoice:
        return _FakeVoice(scripted_chunks=chunks)

    return loader


def _req(text: str = "привет") -> TtsRequest:
    return TtsRequest(text=text, language=Language.RU)


class TestPiperTts:
    async def test_missing_runtime_raises(self) -> None:
        tts = PiperTts(PiperConfig(voice_paths={"ru": "/nonexistent"}))
        with pytest.raises(PiperRuntimeNotAvailableError):
            await tts.synthesize(_req())

    async def test_unconfigured_language_raises(self) -> None:
        tts = PiperTts(
            PiperConfig(voice_paths={"en": "/x.onnx"}),
            loader=_mk_loader([b"pcm"]),
        )
        with pytest.raises(PiperVoiceNotConfiguredError, match="ru"):
            await tts.synthesize(_req())

    async def test_batch_produces_single_frame_with_full_pcm(self) -> None:
        tts = PiperTts(
            PiperConfig(voice_paths={"ru": "/x.onnx"}),
            loader=_mk_loader([b"\x00\x01\x02\x03", b"\x04\x05\x06\x07"]),
        )
        frame = await tts.synthesize(_req())
        assert frame.pcm == b"\x00\x01\x02\x03\x04\x05\x06\x07"
        assert frame.format.sample_rate_hz == 22_050

    async def test_stream_slices_into_chunks(self) -> None:
        # 22.05 kHz * 1ch * 2B = 44_100 B/s; 50 ms = 2205 B chunk.
        piece = b"\x00" * 2200
        tts = PiperTts(
            PiperConfig(voice_paths={"ru": "/x.onnx"}, stream_chunk_ms=50),
            loader=_mk_loader([piece, piece]),
        )
        frames = [f async for f in tts.synthesize_stream(_req())]
        # Total 4400 B → one 2205 B + one 2195 B tail.
        assert sum(len(f.pcm) for f in frames) == 4400
        assert len(frames) == 2
        assert len(frames[0].pcm) == 2205
        assert len(frames[1].pcm) == 4400 - 2205

    async def test_voice_cached_after_first_call(self) -> None:
        calls: list[str] = []

        def loader(path: str) -> _FakeVoice:
            calls.append(path)
            return _FakeVoice(scripted_chunks=[b"\x00\x00"])

        tts = PiperTts(PiperConfig(voice_paths={"ru": "/x.onnx"}), loader=loader)
        await tts.synthesize(_req())
        await tts.synthesize(_req("ещё"))
        assert calls == ["/x.onnx"]
