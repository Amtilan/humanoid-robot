"""Cloud transcription on top of the local ASR.

When the operator switches the AI to a cloud backend in the app (Ещё →
«Модель ИИ»), the same token also routes transcription through the
provider's OpenAI-compatible ``/v1/audio/transcriptions`` endpoint.
The local faster-whisper stays as the fallback: any cloud failure (no
audio API on the provider, network down, bad key) degrades to the local
model for that utterance instead of going deaf.
"""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from humanoid_robot.domain.voice import Language, Transcription
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import AsrPort, AsrStreamChunk, AudioFrame

_LOG = get_logger("cortex-voice.cloud_asr")

_CLOUD_TIMEOUT_S = 20.0
_DEFAULT_CLOUD_MODEL = "whisper-1"


def pcm16_to_wav(pcm: bytes, sample_rate_hz: int, channels: int = 1) -> bytes:
    """Wrap raw little-endian PCM16 in a minimal WAV container."""
    byte_rate = sample_rate_hz * channels * 2
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVE",
            b"fmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate_hz, byte_rate, channels * 2, 16),
            b"data",
            struct.pack("<I", len(pcm)),
            pcm,
        ]
    )


@dataclass(frozen=True)
class _CloudAsrConfig:
    base_url: str
    api_key: str
    model: str = _DEFAULT_CLOUD_MODEL


class SwitchableAsr:
    """AsrPort wrapper: local by default, cloud when a token is configured."""

    def __init__(self, local: AsrPort) -> None:
        self._local = local
        self._cloud: _CloudAsrConfig | None = None

    def reconfigure_cloud(self, *, base_url: str, api_key: str, model: str = "") -> None:
        self._cloud = _CloudAsrConfig(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model or _DEFAULT_CLOUD_MODEL,
        )
        _LOG.info("cloud_asr.enabled", base_url=self._cloud.base_url, model=self._cloud.model)

    def reset_local(self) -> None:
        if self._cloud is not None:
            _LOG.info("cloud_asr.disabled")
        self._cloud = None

    def transcribe_stream(
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        return self._local.transcribe_stream(frames, language_hint=language_hint)

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        cloud = self._cloud
        if cloud is not None:
            try:
                return await self._transcribe_cloud(
                    cloud, pcm, sample_rate_hz=sample_rate_hz, language_hint=language_hint
                )
            except Exception as exc:
                _LOG.warning("cloud_asr.failed_falling_back", error=str(exc))
        return await self._local.transcribe_batch(
            pcm, sample_rate_hz=sample_rate_hz, language_hint=language_hint
        )

    async def _transcribe_cloud(
        self,
        cloud: _CloudAsrConfig,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None,
    ) -> Transcription:
        data: dict[str, str] = {"model": cloud.model, "response_format": "json"}
        if language_hint is not None and language_hint is not Language.UNKNOWN:
            data["language"] = language_hint.value
        async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
            response = await client.post(
                f"{cloud.base_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {cloud.api_key}"},
                data=data,
                files={"file": ("utterance.wav", pcm16_to_wav(pcm, sample_rate_hz), "audio/wav")},
            )
            response.raise_for_status()
            text = str(response.json().get("text", "")).strip()
        return Transcription(
            text=text,
            language=language_hint or Language.UNKNOWN,
            confidence=0.9,
        )
