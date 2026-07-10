"""Robot telemetry cache — remembers the latest sample per `kind`.

Subscribes to ``robot.telemetry`` on the bus and stores the most recent
event.  Callers ask for the whole map or a single kind.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from humanoid_robot.events import BaseEvent, RobotTelemetry
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-core.robot_telemetry_cache")


class RobotTelemetrySample(BaseModel):
    """Read model returned by the cache."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    payload: dict[str, object]
    observed_at: str
    producer: str


@dataclass(slots=True)
class RobotTelemetryCache:
    _samples: dict[str, RobotTelemetrySample] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _subscription: Subscription | None = None

    async def start(self, bus: EventBusPort) -> Subscription:
        sub = await bus.subscribe(RobotTelemetry.subject, self._on_event)
        self._subscription = sub
        _LOG.info("robot_telemetry_cache.ready")
        return sub

    async def stop(self) -> None:
        if self._subscription is not None:
            with contextlib.suppress(Exception):
                await self._subscription.cancel()
            self._subscription = None

    async def all(self) -> tuple[RobotTelemetrySample, ...]:
        async with self._lock:
            return tuple(self._samples.values())

    async def get(self, kind: str) -> RobotTelemetrySample | None:
        async with self._lock:
            return self._samples.get(kind)

    async def _on_event(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotTelemetry):
            return
        sample = RobotTelemetrySample(
            kind=event.kind,
            payload=dict(event.payload),
            observed_at=event.meta.occurred_at.isoformat(),
            producer=event.meta.producer,
        )
        async with self._lock:
            self._samples[event.kind] = sample
