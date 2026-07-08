"""Null AudioInPort / AudioOutPort implementations.

`NullAudioIn` emits silence frames on a monotonic wall-clock schedule so
downstream VAD / wake-word / ASR see a real-time input. `NullAudioOut`
accepts frames and records the total byte count for observability.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import AudioFormat
from humanoid_robot.ports.robot import AudioFrame


class NullAudioInConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_rate_hz: int = Field(default=16_000, gt=0, le=192_000)
    channels: int = Field(default=1, ge=1, le=8)
    sample_width_bytes: int = Field(default=2, ge=1, le=4)
    frame_ms: int = Field(default=50, ge=10, le=200)


@dataclass(slots=True)
class NullAudioIn:
    """Emits silent frames at wall-clock rate."""

    config: NullAudioInConfig = field(default_factory=NullAudioInConfig)
    _closed: bool = field(default=False, init=False)

    def stream(self) -> AsyncIterator[AudioFrame]:
        async def _gen() -> AsyncIterator[AudioFrame]:
            fmt = AudioFormat(
                sample_rate_hz=self.config.sample_rate_hz,
                channels=self.config.channels,
                sample_width_bytes=self.config.sample_width_bytes,
            )
            frame_bytes = fmt.bytes_per_second * self.config.frame_ms // 1000
            silence = b"\x00" * frame_bytes
            interval_s = self.config.frame_ms / 1000.0
            while True:
                await asyncio.sleep(interval_s)
                # `_closed` may be flipped asynchronously by `close()` at any
                # point; we re-read on every iteration and exit cleanly. The
                # while-True + break shape avoids mypy narrowing the flag.
                if self._closed:
                    break
                yield AudioFrame(pcm=silence, format=fmt, monotonic_ns=time.monotonic_ns())

        return _gen()

    async def close(self) -> None:
        self._closed = True


@dataclass(slots=True)
class NullAudioOut:
    """Discards frames; keeps a byte counter for observability."""

    played_bytes: int = 0

    async def play(self, frame: AudioFrame) -> None:
        self.played_bytes += len(frame.pcm)

    async def flush(self) -> None:
        return

    async def stop(self) -> None:
        return


def build_null_audio_in(**kwargs: object) -> NullAudioIn:
    """Entry-point factory — accepts the flat kwargs the CLI passes."""
    return NullAudioIn(config=NullAudioInConfig.model_validate(kwargs))


def build_null_audio_out(**_kwargs: object) -> NullAudioOut:
    """Entry-point factory — no configuration options."""
    return NullAudioOut()
