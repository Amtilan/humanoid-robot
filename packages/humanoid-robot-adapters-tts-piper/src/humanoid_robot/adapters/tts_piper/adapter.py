"""TtsPort implementation using Piper.

Design:
    - Voice files (`ru_RU-…-medium.onnx`) are loaded lazily on first use for
      each language. Multiple voices coexist in one adapter — the request's
      `.language` + optional `.voice_id` selects which one.
    - `synthesize(request)` returns one `AudioFrame` containing the whole
      utterance's PCM. `synthesize_stream(request)` yields frames as Piper
      emits them, so downstream can start playback before synthesis finishes.
    - Runtime dependency `piper-tts` is optional; a loader callable can be
      injected in tests to avoid any real ONNX work.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import AudioFormat, Language
from humanoid_robot.ports.ai import TtsRequest
from humanoid_robot.ports.robot import AudioFrame

_DEFAULT_STREAM_CHUNK_MS = 50


class PiperRuntimeNotAvailableError(RuntimeError):
    """Raised when `piper-tts` is not installed at runtime."""

    def __init__(self) -> None:
        super().__init__(
            "piper-tts is not installed. Install this adapter with its runtime "
            "extra: uv add 'humanoid-robot-adapters-tts-piper[runtime]'"
        )


class PiperVoiceNotConfiguredError(RuntimeError):
    """Requested language / voice was not registered on the adapter."""


class PiperConfig(BaseModel):
    """Adapter-level configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    voice_paths: dict[str, str] = Field(default_factory=dict)
    default_language: Language = Language.RU
    stream_chunk_ms: int = Field(default=_DEFAULT_STREAM_CHUNK_MS, ge=10, le=500)


@dataclass(slots=True)
class PiperTts:
    """Piper-backed TtsPort."""

    config: PiperConfig
    _loader: Any = None
    _voices: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        config: PiperConfig | None = None,
        *,
        loader: Any = None,
        **kwargs: Any,
    ) -> None:
        # Voice composition resolves adapters as ``factory(**selection.config)``,
        # so a YAML `config:` block arrives as flat keyword args — build the
        # config model from them. An explicit `config=` (tests) still wins.
        if config is None and kwargs:
            config = PiperConfig(**kwargs)
        self.config = config or PiperConfig()
        self._loader = loader
        self._voices = {}

    async def synthesize(self, request: TtsRequest) -> AudioFrame:
        voice = self._resolve_voice(request.language)
        pcm = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: b"".join(c.audio_int16_bytes for c in voice.synthesize(request.text)),
        )
        fmt = _voice_format(voice)
        return AudioFrame(pcm=pcm, format=fmt, monotonic_ns=time.monotonic_ns())

    async def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]:
        voice = self._resolve_voice(request.language)
        fmt = _voice_format(voice)
        chunk_bytes = _chunk_bytes(fmt, self.config.stream_chunk_ms)

        # Run the (potentially blocking) synthesizer in a worker thread; pump
        # its raw output into an asyncio.Queue so we can `await` chunks.
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=8)
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                for chunk in voice.synthesize(request.text):
                    asyncio.run_coroutine_threadsafe(
                        queue.put(chunk.audio_int16_bytes), loop
                    ).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        producer_task = loop.run_in_executor(None, _produce)

        buffer = bytearray()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                buffer.extend(item)
                while len(buffer) >= chunk_bytes:
                    slice_ = bytes(buffer[:chunk_bytes])
                    del buffer[:chunk_bytes]
                    yield AudioFrame(
                        pcm=slice_,
                        format=fmt,
                        monotonic_ns=time.monotonic_ns(),
                    )
            if buffer:
                yield AudioFrame(
                    pcm=bytes(buffer),
                    format=fmt,
                    monotonic_ns=time.monotonic_ns(),
                )
        finally:
            await producer_task

    def _resolve_voice(self, language: Language) -> Any:
        key = (
            language.value
            if language is not Language.UNKNOWN
            else self.config.default_language.value
        )
        voice = self._voices.get(key)
        if voice is not None:
            return voice

        path = self.config.voice_paths.get(key)
        if path is None:
            msg = (
                f"no Piper voice configured for language {key!r}; "
                f"configured: {sorted(self.config.voice_paths)}"
            )
            raise PiperVoiceNotConfiguredError(msg)

        if self._loader is not None:
            voice = self._loader(path)
        else:
            try:
                piper_voice = importlib.import_module("piper.voice")
            except ImportError as exc:
                raise PiperRuntimeNotAvailableError from exc
            voice = piper_voice.PiperVoice.load(path)

        self._voices[key] = voice
        return voice


def _voice_format(voice: Any) -> AudioFormat:
    """Read sample-rate/channels/width from a Piper voice's config."""
    cfg = getattr(voice, "config", None)
    sample_rate_hz = getattr(cfg, "sample_rate", None) or 22_050
    return AudioFormat(sample_rate_hz=int(sample_rate_hz), channels=1, sample_width_bytes=2)


def _chunk_bytes(fmt: AudioFormat, chunk_ms: int) -> int:
    # Align to a whole audio frame (e.g. 2 bytes for mono PCM16) — an odd-sized
    # chunk breaks downstream 16-bit consumers like audioop.ratecv ("not a
    # whole number of frames"). At 22050 Hz mono, 50 ms would be 2205 (odd).
    frame = fmt.sample_width_bytes * fmt.channels
    raw = fmt.bytes_per_second * chunk_ms // 1000
    return max(frame, raw - raw % frame)
