"""WakeWordPort implementation using openWakeWord.

Design:
    - Lazy import of `openwakeword` — package installs cleanly on any laptop.
    - Buffers PCM to the native 1280-sample frame; on each full frame, calls
      the detector and returns the highest-scoring word above threshold, or
      None.
    - Detector is injectable via `detector` kwarg for tests.
"""

from __future__ import annotations

import importlib
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.ports.robot import AudioFrame
from humanoid_robot.ports.voice import WakeWordEvent

_MODEL_SAMPLE_RATE_HZ = 16_000
_MODEL_FRAME_SAMPLES = 1_280
_PCM16_SAMPLE_WIDTH_BYTES = 2
_MONO_CHANNELS = 1
_MODEL_FRAME_BYTES = _MODEL_FRAME_SAMPLES * _PCM16_SAMPLE_WIDTH_BYTES


class OpenWakeWordRuntimeNotAvailableError(RuntimeError):
    """Raised when the openWakeWord runtime dependency is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "openwakeword is not installed. Install this adapter with its "
            "runtime extra: uv add "
            "'humanoid-robot-adapters-wakeword-openwakeword[runtime]'"
        )


class OpenWakeWordConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_paths: tuple[str, ...] = ()
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


# Detector signature: takes an iterable of int16 samples, returns a mapping
# from label to a float score.
Detector = Callable[[list[int]], dict[str, float]]


@dataclass(slots=True)
class OpenWakeWord:
    """openWakeWord-backed WakeWordPort."""

    config: OpenWakeWordConfig
    _detector: Detector | None = None
    _buffer: bytearray = field(default_factory=bytearray)

    def __init__(
        self,
        config: OpenWakeWordConfig | None = None,
        *,
        detector: Detector | None = None,
    ) -> None:
        self.config = config or OpenWakeWordConfig()
        self._detector = detector
        self._buffer = bytearray()

    async def feed(self, frame: AudioFrame) -> WakeWordEvent | None:
        if frame.format.sample_rate_hz != _MODEL_SAMPLE_RATE_HZ:
            msg = f"openWakeWord requires {_MODEL_SAMPLE_RATE_HZ} Hz input"
            raise ValueError(msg)
        if (
            frame.format.sample_width_bytes != _PCM16_SAMPLE_WIDTH_BYTES
            or frame.format.channels != _MONO_CHANNELS
        ):
            msg = "openWakeWord requires mono 16-bit PCM"
            raise ValueError(msg)

        self._buffer.extend(frame.pcm)
        detector = self._resolve_detector()

        best: WakeWordEvent | None = None
        while len(self._buffer) >= _MODEL_FRAME_BYTES:
            chunk = self._buffer[:_MODEL_FRAME_BYTES]
            del self._buffer[:_MODEL_FRAME_BYTES]
            samples = _pcm16_to_int_list(bytes(chunk))
            scores = detector(samples)
            for word, score in scores.items():
                if score >= self.config.threshold and (best is None or score > best.score):
                    best = WakeWordEvent(word=word, score=float(score))
        return best

    def keywords(self) -> tuple[str, ...]:
        return tuple(Path(p).stem for p in self.config.model_paths)

    def _resolve_detector(self) -> Detector:
        if self._detector is not None:
            return self._detector
        try:
            oww = importlib.import_module("openwakeword.model")
        except ImportError as exc:
            raise OpenWakeWordRuntimeNotAvailableError from exc
        model = oww.Model(
            wakeword_models=list(self.config.model_paths),
            inference_framework="onnx",
        )

        def _predict(samples: list[int]) -> dict[str, float]:
            import numpy as np

            arr = np.array(samples, dtype=np.int16)
            prediction = model.predict(arr)
            return {k: float(v) for k, v in prediction.items()}

        self._detector = _predict
        return _predict


def _pcm16_to_int_list(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))
