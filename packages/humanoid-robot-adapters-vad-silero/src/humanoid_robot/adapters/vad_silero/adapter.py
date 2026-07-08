"""VadPort implementation using Silero VAD v5.

Design:
    - Frame accumulator: model wants 512 samples at 16 kHz. Callers can push
      any size — we buffer, and evaluate the model as soon as we have a full
      frame. Partial residues carry forward.
    - `_predictor` is injected in tests as a callable that takes a
      512-sample float32 iterable and returns a probability [0.0, 1.0].
"""

from __future__ import annotations

import importlib
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.ports.voice import VadDecision

_MODEL_SAMPLE_RATE_HZ = 16_000
_MODEL_FRAME_SAMPLES = 512
_PCM16_SAMPLE_WIDTH_BYTES = 2
_MONO_CHANNELS = 1
_MODEL_FRAME_BYTES = _MODEL_FRAME_SAMPLES * _PCM16_SAMPLE_WIDTH_BYTES


class SileroRuntimeNotAvailableError(RuntimeError):
    """Raised when the Silero runtime dependency is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "silero-vad is not installed. Install this adapter with its runtime "
            "extra: uv add 'humanoid-robot-adapters-vad-silero[runtime]'"
        )


class SileroConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


@dataclass(slots=True)
class SileroVad:
    """Silero VAD v5 wrapper."""

    config: SileroConfig
    _predictor: Callable[[list[float]], float] | None = None
    _buffer: bytearray = field(default_factory=bytearray)
    _last_probability: float = 0.0

    def __init__(
        self,
        config: SileroConfig | None = None,
        *,
        predictor: Callable[[list[float]], float] | None = None,
    ) -> None:
        self.config = config or SileroConfig()
        self._predictor = predictor
        self._buffer = bytearray()
        self._last_probability = 0.0

    async def decide(self, frame: AudioFrame) -> VadDecision:
        if frame.format.sample_rate_hz != _MODEL_SAMPLE_RATE_HZ:
            msg = f"Silero VAD requires {_MODEL_SAMPLE_RATE_HZ} Hz input"
            raise ValueError(msg)
        if (
            frame.format.sample_width_bytes != _PCM16_SAMPLE_WIDTH_BYTES
            or frame.format.channels != _MONO_CHANNELS
        ):
            msg = "Silero VAD requires mono 16-bit PCM"
            raise ValueError(msg)

        self._buffer.extend(frame.pcm)
        predictor = self._resolve_predictor()

        while len(self._buffer) >= _MODEL_FRAME_BYTES:
            chunk = self._buffer[:_MODEL_FRAME_BYTES]
            del self._buffer[:_MODEL_FRAME_BYTES]
            samples = _pcm16_to_float32(bytes(chunk))
            self._last_probability = float(predictor(samples))

        return VadDecision(
            is_speech=self._last_probability >= self.config.threshold,
            speech_probability=self._last_probability,
        )

    async def reset(self) -> None:
        self._buffer.clear()
        self._last_probability = 0.0

    def _resolve_predictor(self) -> Callable[[list[float]], float]:
        if self._predictor is not None:
            return self._predictor
        try:
            silero_vad = importlib.import_module("silero_vad")
        except ImportError as exc:
            raise SileroRuntimeNotAvailableError from exc
        model: Any = silero_vad.load_silero_vad(onnx=True)

        def _predict(samples: list[float]) -> float:
            import numpy as np  # noqa: PLC0415 — runtime-optional dep

            tensor = np.array(samples, dtype=np.float32)
            return float(model(tensor, _MODEL_SAMPLE_RATE_HZ))

        self._predictor = _predict
        return _predict


def _pcm16_to_float32(pcm: bytes) -> list[float]:
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    return [s / 32768.0 for s in samples]
