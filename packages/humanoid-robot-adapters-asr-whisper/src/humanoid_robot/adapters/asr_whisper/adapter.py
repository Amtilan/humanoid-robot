"""AsrPort implementation using faster-whisper.

Design:
    - Lazy import of `faster_whisper` and `numpy` — package imports cleanly
      on any laptop; runtime deps come from the `[runtime]` extra.
    - Deterministic per-instance loader: model is loaded on first use
      inside `transcribe_batch` / `transcribe_stream`.
    - Streaming wrapper: consume `AudioFrame`s from an async iterator,
      buffer until `partial_interval_ms` has elapsed, decode with
      `condition_on_previous=False`, emit an `AsrStreamChunk` with
      `is_final=False`. On iterator close, run one final decode with
      `beam_size` and emit `is_final=True`.
"""

from __future__ import annotations

import asyncio
import importlib
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import Language, Transcription
from humanoid_robot.ports.ai import AsrStreamChunk
from humanoid_robot.ports.robot import AudioFrame


class WhisperRuntimeNotAvailableError(RuntimeError):
    """Raised when `faster-whisper` is not installed at runtime."""

    def __init__(self) -> None:
        super().__init__(
            "faster-whisper is not installed. Install this adapter with its "
            "runtime extra: uv add 'humanoid-robot-adapters-asr-whisper[runtime]'"
        )


class FasterWhisperConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = "large-v3-turbo"
    compute_type: str = "int8"
    device: str = "cuda"
    default_language: Language = Language.RU
    beam_size: int = Field(default=5, ge=1, le=10)
    partial_interval_ms: int = Field(default=300, ge=100, le=2000)
    sample_rate_hz: int = 16_000


@dataclass(slots=True)
class FasterWhisperAsr:
    """AsrPort backed by faster-whisper CT2."""

    config: FasterWhisperConfig
    _loader: Any = None  # injected fake in tests
    _model: Any = None

    def __init__(
        self,
        config: FasterWhisperConfig | None = None,
        *,
        loader: Any = None,
        **kwargs: Any,
    ) -> None:
        # The voice composition resolves adapters as ``factory(**selection.config)``,
        # so a YAML `config:` block arrives as flat keyword args — build the
        # config model from them. An explicit `config=` (tests) still wins.
        if config is None and kwargs:
            config = FasterWhisperConfig(**kwargs)
        self.config = config or FasterWhisperConfig()
        self._loader = loader
        self._model = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._loader is not None:
            self._model = self._loader(self.config)
            return self._model
        try:
            fw = importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise WhisperRuntimeNotAvailableError from exc
        self._model = fw.WhisperModel(
            self.config.model_id,
            device=self.config.device,
            compute_type=self.config.compute_type,
        )
        return self._model

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription:
        if sample_rate_hz != self.config.sample_rate_hz:
            msg = (
                f"faster-whisper adapter expects {self.config.sample_rate_hz} Hz, "
                f"got {sample_rate_hz} Hz — resample upstream"
            )
            raise ValueError(msg)

        model = self._ensure_model()
        language = language_hint or self.config.default_language
        audio = _pcm16_to_float32(pcm)

        # `transcribe` may block for hundreds of ms; run in a worker thread so
        # the caller's event loop stays responsive.
        loop = asyncio.get_running_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(
                audio,
                language=None if language is Language.UNKNOWN else language.value,
                beam_size=self.config.beam_size,
                vad_filter=False,
            ),
        )
        segments_list = list(segments)
        text = "".join(seg.text for seg in segments_list).strip()

        detected = getattr(info, "language", None) or language.value
        try:
            detected_language = Language(detected)
        except ValueError:
            detected_language = Language.UNKNOWN
        confidence = getattr(info, "language_probability", None) or 1.0

        return Transcription(
            text=text,
            language=detected_language,
            confidence=float(confidence),
        )

    async def transcribe_stream(
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]:
        buffer = bytearray()
        stable_prefix_len = 0
        last_partial_bytes = 0
        bytes_per_ms = self.config.sample_rate_hz * 2 // 1000

        async for frame in frames:
            if frame.format.sample_rate_hz != self.config.sample_rate_hz:
                msg = "stream frames must match adapter sample_rate_hz"
                raise ValueError(msg)
            buffer.extend(frame.pcm)
            elapsed_ms = (len(buffer) - last_partial_bytes) // bytes_per_ms
            if elapsed_ms >= self.config.partial_interval_ms:
                partial = await self.transcribe_batch(
                    bytes(buffer),
                    sample_rate_hz=self.config.sample_rate_hz,
                    language_hint=language_hint,
                )
                yield AsrStreamChunk(
                    text=partial.text,
                    is_final=False,
                    stable_prefix_len=stable_prefix_len,
                )
                stable_prefix_len = len(partial.text)
                last_partial_bytes = len(buffer)

        final = await self.transcribe_batch(
            bytes(buffer),
            sample_rate_hz=self.config.sample_rate_hz,
            language_hint=language_hint,
        )
        yield AsrStreamChunk(
            text=final.text,
            is_final=True,
            stable_prefix_len=len(final.text),
        )


def _pcm16_to_float32(pcm: bytes) -> list[float]:
    if not pcm:
        return []
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    return [s / 32768.0 for s in samples]
