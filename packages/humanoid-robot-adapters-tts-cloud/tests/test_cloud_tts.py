"""CloudTts: OpenAI-compatible speech requests + per-language voices."""

from __future__ import annotations

import io
import json
import wave

import httpx
import pytest

from humanoid_robot.adapters.tts_cloud.adapter import CloudTts, CloudTtsConfig
from humanoid_robot.domain.voice import Language
from humanoid_robot.ports import TtsRequest


def _wav(sample_rate: int = 22_050, samples: int = 1_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x01\x00" * samples)
    return buffer.getvalue()


def _adapter(seen: list[dict[str, object]]) -> CloudTts:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, content=_wav())

    return CloudTts(
        CloudTtsConfig(
            base_url="https://tts.example",
            api_key="test-key",  # pragma: allowlist secret
            voices={"ru": "marina", "kk": "madi"},
        ),
        transport=httpx.MockTransport(handler),
    )


async def test_synthesize_parses_wav_and_picks_kazakh_voice() -> None:
    seen: list[dict[str, object]] = []
    adapter = _adapter(seen)
    frame = await adapter.synthesize(TtsRequest(text="Сәлеметсіз бе!", language=Language.KK))
    assert frame.format.sample_rate_hz == 22_050
    assert frame.format.channels == 1
    assert len(frame.pcm) == 2_000
    assert seen[0]["voice"] == "madi"
    assert seen[0]["input"] == "Сәлеметсіз бе!"
    await adapter.close()


async def test_stream_is_single_frame_and_ru_voice() -> None:
    seen: list[dict[str, object]] = []
    adapter = _adapter(seen)
    frames = [
        f
        async for f in adapter.synthesize_stream(
            TtsRequest(text="Здравствуйте", language=Language.RU)
        )
    ]
    assert len(frames) == 1
    assert seen[0]["voice"] == "marina"
    await adapter.close()


async def test_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    adapter = CloudTts(
        CloudTtsConfig(base_url="https://tts.example", api_key="k"),  # pragma: allowlist secret
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.synthesize(TtsRequest(text="x", language=Language.RU))
    await adapter.close()
