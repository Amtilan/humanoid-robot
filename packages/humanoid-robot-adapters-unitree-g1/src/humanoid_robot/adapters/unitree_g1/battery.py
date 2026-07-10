"""BatteryPort implementation for the Unitree G1.

The vendor SDK exposes battery telemetry via the LowLevelSubscriber's
`bms_state` field.  Because the fixture only fires on a background DDS
thread, we cache the last percentage under a lock and hand it back
synchronously from `read_percentage()`.

Off-robot the SDK isn't importable, so the adapter accepts either a
callable that returns a percentage in `[0, 1]` (fake path) or is left
uninitialised — in which case `read_percentage()` reports 0.0 rather
than raising.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from humanoid_robot.observability import get_logger

_LOG = get_logger("cortex-adapters.g1.battery")


@dataclass(slots=True)
class UnitreeG1Battery:
    """A cached battery percentage source.

    ``source`` — optional zero-arg callable returning percentage in
    [0.0, 1.0].  If omitted, the adapter reports the last value passed
    through ``set_percentage`` (for tests) and 0.0 before anything sets
    one.  Real hardware wires a subscriber that calls ``set_percentage``
    on every DDS tick.
    """

    source: Callable[[], float] | None = None
    _last: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def read_percentage(self) -> float:
        source = self.source
        if source is not None:
            try:
                value = float(source())
            except Exception:
                _LOG.exception("g1.battery.source_failed")
                async with self._lock:
                    return self._last
            value = max(0.0, min(1.0, value))
            async with self._lock:
                self._last = value
            return value
        async with self._lock:
            return self._last

    async def set_percentage(self, value: float) -> None:
        async with self._lock:
            self._last = max(0.0, min(1.0, float(value)))
