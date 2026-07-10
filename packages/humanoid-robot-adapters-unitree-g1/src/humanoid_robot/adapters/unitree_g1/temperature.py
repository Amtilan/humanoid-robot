"""Temperature adapter for the Unitree G1.

Same shape as the battery/IMU adapters: a caller-provided ``source``
callable returns the latest temperature sample as a
``dict[str, float]`` (per-zone Celsius values).  Cached under a lock so
polling doesn't block the DDS thread.

The G1 exposes at least ``cpu``, ``battery``, ``motor_left_hip`` etc.
via LowLevelSubscriber's ``temperature_state``; the adapter is agnostic
to which zones appear — it passes them through unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from humanoid_robot.observability import get_logger

_LOG = get_logger("cortex-adapters.g1.temperature")

# Sample shape: {"cpu": 62.5, "battery": 34.0, ...}
TemperatureSample = dict[str, float]


@dataclass(slots=True)
class UnitreeG1Temperature:
    """Cached temperature sample source."""

    source: Callable[[], TemperatureSample] | None = None
    _last: TemperatureSample = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def read(self) -> TemperatureSample:
        source = self.source
        if source is not None:
            try:
                sample = _sanitise(source())
            except Exception:
                _LOG.exception("g1.temperature.source_failed")
                async with self._lock:
                    return dict(self._last)
            async with self._lock:
                self._last = sample
            return dict(sample)
        async with self._lock:
            return dict(self._last)

    async def push(self, sample: TemperatureSample) -> None:
        """DDS callback path — replaces the cached sample."""
        clean = _sanitise(sample)
        async with self._lock:
            self._last = clean


def _sanitise(sample: object) -> TemperatureSample:
    if not isinstance(sample, dict):
        return {}
    out: TemperatureSample = {}
    for key, value in sample.items():
        if not isinstance(key, str):
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out
