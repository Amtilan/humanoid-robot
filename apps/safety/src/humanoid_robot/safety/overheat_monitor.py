"""OverheatMonitor — auto-engage e-stop when any zone crosses the temperature limit.

Subscribes to ``robot.telemetry`` events of ``kind="temperature"`` and
reads every value in the payload as a Celsius sample.  If any zone's
reading exceeds ``max_temperature_c``, it asks the gate to engage the
e-stop.  Edge-triggered like the TiltMonitor: only fires on the
safe→unsafe transition.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from humanoid_robot.events import BaseEvent, RobotTelemetry
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.safety.gate import SafetyGate

_LOG = get_logger("cortex-safety.overheat_monitor")


@dataclass(slots=True)
class OverheatMonitor:
    """Fires the e-stop when any temperature zone crosses the limit."""

    gate: SafetyGate
    bus: EventBusPort
    max_temperature_c: float = 85.0
    actor: str = "overheat-monitor"
    _subscription: Subscription | None = None
    _was_safe: bool = True
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if self._subscription is not None:
            return
        self._subscription = await self.bus.subscribe(RobotTelemetry.subject, self._on_event)
        _LOG.info("overheat_monitor.ready", max_temperature_c=self.max_temperature_c)

    async def stop(self) -> None:
        if self._subscription is not None:
            with contextlib.suppress(Exception):
                await self._subscription.cancel()
            self._subscription = None

    async def _on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotTelemetry):
            return
        if event.kind != "temperature":
            return
        offenders = _offenders(event.payload, self.max_temperature_c)
        safe = not offenders
        async with self._lock:
            was_safe = self._was_safe
            self._was_safe = safe
        if safe or not was_safe:
            return
        # Sort so the log/reason is stable across runs.
        offenders.sort(key=lambda kv: kv[1], reverse=True)
        top = offenders[0]
        reason = (
            f"overheat: {top[0]} at {top[1]:.1f}°C exceeds "
            f"{self.max_temperature_c:.1f}°C ({len(offenders)} zones over limit)"
        )
        engaged = await self.gate.engage_estop(actor=self.actor, reason=reason)
        if engaged:
            _LOG.warning(
                "overheat_monitor.estop_engaged",
                zone=top[0],
                celsius=top[1],
                zones_over=len(offenders),
            )


def _offenders(payload: dict[str, object], limit: float) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, (int, float)):
            continue
        celsius = float(value)
        if celsius > limit:
            out.append((key, celsius))
    return out
