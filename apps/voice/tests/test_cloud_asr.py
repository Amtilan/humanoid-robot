"""SwitchableAsr — cloud transcription with local fallback."""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from humanoid_robot.domain.voice import Language, Transcription
from humanoid_robot.ports import AsrStreamChunk, AudioFrame
from humanoid_robot.voice.cloud_asr import SwitchableAsr, pcm16_to_wav


class _FakeLocalAsr:
    def __init__(self) -> None:
        self.batch_calls = 0

    def transcribe_stream(
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        raise NotImplementedError

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        self.batch_calls += 1
        return Transcription(text="локально", language=Language.RU, confidence=1.0)


def _patch_cloud(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)


async def test_local_by_default() -> None:
    local = _FakeLocalAsr()
    asr = SwitchableAsr(local)
    result = await asr.transcribe_batch(b"\x00\x00", sample_rate_hz=16000)
    assert result.text == "локально"
    assert local.batch_calls == 1


async def test_cloud_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"text": " из облака "})

    _patch_cloud(monkeypatch, handler)
    local = _FakeLocalAsr()
    asr = SwitchableAsr(local)
    asr.reconfigure_cloud(
        base_url="https://api.openai.com/",
        api_key="sk-test",  # pragma: allowlist secret
    )

    result = await asr.transcribe_batch(
        b"\x00\x00" * 100, sample_rate_hz=16000, language_hint=Language.RU
    )
    assert result.text == "из облака"
    assert local.batch_calls == 0
    assert seen["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer sk-test"


async def test_cloud_failure_falls_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "no audio api"})

    _patch_cloud(monkeypatch, handler)
    local = _FakeLocalAsr()
    asr = SwitchableAsr(local)
    asr.reconfigure_cloud(
        base_url="https://api.deepseek.com",
        api_key="sk-x",  # pragma: allowlist secret
    )

    result = await asr.transcribe_batch(b"\x00\x00", sample_rate_hz=16000)
    assert result.text == "локально"
    assert local.batch_calls == 1


async def test_reset_local_disables_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("cloud must not be called after reset")

    _patch_cloud(monkeypatch, handler)
    local = _FakeLocalAsr()
    asr = SwitchableAsr(local)
    asr.reconfigure_cloud(
        base_url="https://api.openai.com",
        api_key="sk-test",  # pragma: allowlist secret
    )
    asr.reset_local()

    result = await asr.transcribe_batch(b"\x00\x00", sample_rate_hz=16000)
    assert result.text == "локально"


def test_pcm16_to_wav_header() -> None:
    pcm = b"\x01\x02" * 160
    wav = pcm16_to_wav(pcm, 16000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    (rate,) = struct.unpack("<I", wav[24:28])
    assert rate == 16000
    assert wav.endswith(pcm)
