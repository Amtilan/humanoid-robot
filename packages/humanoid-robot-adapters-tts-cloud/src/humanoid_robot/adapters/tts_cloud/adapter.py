"""TtsPort over an OpenAI-compatible ``/v1/audio/speech`` endpoint.

The provider returns a complete WAV per request; ``synthesize_stream`` yields
it as one frame — the voice pipeline already streams sentence-by-sentence, so
per-sentence latency stays low. Any failure raises; pair with the local Piper
via the voice service's ``tts_fallback`` so the robot keeps speaking offline.
"""

from __future__ import annotations

import io
import os
import time
import wave
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports import AudioFrame, TtsRequest

_DEFAULT_TIMEOUT_S = 30.0


class CloudTtsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "https://api.openai.com"
    # The key never lives in YAML/git — only the env var name does.
    api_key: str = ""
    api_key_env: str = "HR_TTS_CLOUD_API_KEY"
    model: str = "tts-1"
    # Voice per BCP-47 language ("ru", "kk", "en"); the whole point of the
    # cloud adapter is a real Kazakh voice.
    voices: dict[str, str] = Field(default_factory=dict)
    default_voice: str = "alloy"
    speed: float = Field(gt=0.0, le=2.0, default=1.0)
    timeout_s: float = _DEFAULT_TIMEOUT_S


class CloudTts:
    """OpenAI-compatible speech synthesis client."""

    def __init__(
        self,
        config: CloudTtsConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        if config is None and kwargs:
            config = CloudTtsConfig(**kwargs)
        self.config = config or CloudTtsConfig()
        self._client = httpx.AsyncClient(timeout=self.config.timeout_s, transport=transport)

    def _api_key(self) -> str:
        return self.config.api_key or os.environ.get(self.config.api_key_env, "")

    def _voice_for(self, request: TtsRequest) -> str:
        if request.voice_id:
            return request.voice_id
        return self.config.voices.get(str(request.language.value), self.config.default_voice)

    async def synthesize(self, request: TtsRequest) -> AudioFrame:
        response = await self._client.post(
            f"{self.config.base_url.rstrip('/')}/v1/audio/speech",
            headers={"Authorization": f"Bearer {self._api_key()}"},
            json={
                "model": self.config.model,
                "input": request.text,
                "voice": self._voice_for(request),
                "response_format": "wav",
                "speed": request.speed * self.config.speed,
            },
        )
        response.raise_for_status()
        pcm, fmt = _parse_wav(response.content)
        return AudioFrame(pcm=pcm, format=fmt, monotonic_ns=time.monotonic_ns())

    async def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]:
        yield await self.synthesize(request)

    async def close(self) -> None:
        await self._client.aclose()


def _parse_wav(data: bytes) -> tuple[bytes, AudioFormat]:
    with wave.open(io.BytesIO(data), "rb") as reader:
        fmt = AudioFormat(
            sample_rate_hz=reader.getframerate(),
            channels=reader.getnchannels(),
            sample_width_bytes=reader.getsampwidth(),
        )
        return reader.readframes(reader.getnframes()), fmt
