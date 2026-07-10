"""IMU adapter for the Unitree G1.

Same shape as the battery adapter: a caller-provided ``source`` callable
returns the latest IMU sample as a ``dict[str, float]`` (pitch/roll/yaw
in radians and optional angular rates).  The last known sample is
cached under a lock so the pump can read at its own cadence without
blocking the DDS thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from humanoid_robot.observability import get_logger

_LOG = get_logger("cortex-adapters.g1.imu")

# Sample shape: {"pitch_rad": …, "roll_rad": …, "yaw_rad": …,
#                "gyro_x": …, "gyro_y": …, "gyro_z": …}
# All extra keys are passed through unchanged so we can carry accel etc.
ImuSample = dict[str, float]


@dataclass(slots=True)
class UnitreeG1Imu:
    """Cached IMU sample source."""

    source: Callable[[], ImuSample] | None = None
    _last: ImuSample = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def read(self) -> ImuSample:
        source = self.source
        if source is not None:
            try:
                sample = _sanitise(source())
            except Exception:
                _LOG.exception("g1.imu.source_failed")
                async with self._lock:
                    return dict(self._last)
            async with self._lock:
                self._last = sample
            return dict(sample)
        async with self._lock:
            return dict(self._last)

    async def push(self, sample: ImuSample) -> None:
        """DDS callback path — replaces the cached sample."""
        clean = _sanitise(sample)
        async with self._lock:
            self._last = clean


def _sanitise(sample: object) -> ImuSample:
    if not isinstance(sample, dict):
        return {}
    out: ImuSample = {}
    for key, value in sample.items():
        if not isinstance(key, str):
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out
