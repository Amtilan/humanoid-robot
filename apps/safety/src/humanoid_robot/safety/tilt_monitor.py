"""TiltMonitor — auto-engage e-stop when the robot tips over.

Subscribes to ``robot.telemetry`` events of ``kind="imu"``, extracts the
pitch/roll (in radians) from the payload, and asks the gate to engage
the e-stop when either exceeds the configured limit.  Only fires on the
edge (safe → unsafe transition) so a robot lying on its side doesn't
generate a storm.

The IMU payload shape is flexible — any of ``pitch_rad``, ``pitch``,
``theta_x`` counts as the pitch angle; likewise for roll.  If neither is
found, the sample is ignored (the robot's IMU may not have booted yet).
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from dataclasses import dataclass, field

from humanoid_robot.events import BaseEvent, RobotTelemetry
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.safety.gate import SafetyGate

_LOG = get_logger("cortex-safety.tilt_monitor")

_PITCH_KEYS = ("pitch_rad", "pitch", "theta_x")
_ROLL_KEYS = ("roll_rad", "roll", "theta_y")


@dataclass(slots=True)
class TiltMonitor:
    """Fires the e-stop when |pitch| or |roll| crosses the limit."""

    gate: SafetyGate
    bus: EventBusPort
    max_pitch_rad: float = 0.6  # ~34°
    max_roll_rad: float = 0.6
    actor: str = "tilt-monitor"
    _subscription: Subscription | None = None
    _was_safe: bool = True
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if self._subscription is not None:
            return
        self._subscription = await self.bus.subscribe(RobotTelemetry.subject, self._on_event)
        _LOG.info(
            "tilt_monitor.ready",
            max_pitch_rad=self.max_pitch_rad,
            max_roll_rad=self.max_roll_rad,
        )

    async def stop(self) -> None:
        if self._subscription is not None:
            with contextlib.suppress(Exception):
                await self._subscription.cancel()
            self._subscription = None

    async def _on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotTelemetry):
            return
        if event.kind != "imu":
            return
        pitch = _pick(event.payload, _PITCH_KEYS)
        roll = _pick(event.payload, _ROLL_KEYS)
        if pitch is None and roll is None:
            return
        pitch = abs(pitch or 0.0)
        roll = abs(roll or 0.0)
        safe = pitch <= self.max_pitch_rad and roll <= self.max_roll_rad
        async with self._lock:
            was_safe = self._was_safe
            self._was_safe = safe
        if safe or not was_safe:
            return
        reason = (
            f"tilt over limit: pitch={math.degrees(pitch):.1f}°, roll={math.degrees(roll):.1f}°"
        )
        engaged = await self.gate.engage_estop(actor=self.actor, reason=reason)
        if engaged:
            _LOG.warning("tilt_monitor.estop_engaged", pitch=pitch, roll=roll)


def _pick(payload: dict[str, object], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
