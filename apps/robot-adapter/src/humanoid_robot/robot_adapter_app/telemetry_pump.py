"""TelemetryPump — periodically samples the adapter and publishes telemetry.

Runs alongside the CommandDispatcher.  Currently pumps battery
percentage (as the first sensor); more kinds (IMU, temperature) can be
added without changing the pump's control flow — each source returns an
opaque ``dict[str, object]`` payload.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotTelemetry
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import BatteryPort, EventBusPort

_LOG = get_logger("cortex-robot-adapter.telemetry_pump")

TelemetrySample = tuple[str, dict[str, object]]  # (kind, payload)
TelemetrySource = Callable[[], Awaitable[TelemetrySample | None]]


def battery_source(port: BatteryPort) -> TelemetrySource:
    async def _sample() -> TelemetrySample | None:
        percentage = await port.read_percentage()
        return ("battery", {"percentage": float(percentage)})

    return _sample


def imu_source(reader: object) -> TelemetrySource:
    """Wraps any object with an async ``read() -> dict[str, float]`` method."""

    async def _sample() -> TelemetrySample | None:
        read = reader.read  # type: ignore[attr-defined]
        payload = await read()
        if not isinstance(payload, dict):
            return None
        cleaned: dict[str, object] = {k: v for k, v in payload.items() if isinstance(k, str)}
        return ("imu", cleaned)

    return _sample


def temperature_source(reader: object) -> TelemetrySource:
    """Wraps any object with an async ``read() -> dict[str, float]`` method."""

    async def _sample() -> TelemetrySample | None:
        read = reader.read  # type: ignore[attr-defined]
        payload = await read()
        if not isinstance(payload, dict):
            return None
        cleaned: dict[str, object] = {k: v for k, v in payload.items() if isinstance(k, str)}
        return ("temperature", cleaned)

    return _sample


@dataclass(slots=True)
class TelemetryPump:
    """Polls each source on a fixed interval and publishes RobotTelemetry."""

    bus: EventBusPort
    sources: list[TelemetrySource] = field(default_factory=list)
    interval_s: float = 5.0
    producer: str = "cortex-robot-adapter"
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def register(self, source: TelemetrySource) -> None:
        self.sources.append(source)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="telemetry-pump")
        _LOG.info("telemetry_pump.ready", sources=len(self.sources))

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            for source in list(self.sources):
                await self._emit_one(source)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)

    async def _emit_one(self, source: TelemetrySource) -> None:
        try:
            sample = await source()
        except Exception:
            _LOG.exception("telemetry_pump.source_failed")
            return
        if sample is None:
            return
        kind, payload = sample
        try:
            await self.bus.publish(
                RobotTelemetry(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer=self.producer,
                    ),
                    kind=kind,
                    payload=payload,
                )
            )
        except Exception:
            _LOG.exception("telemetry_pump.publish_failed", kind=kind)
