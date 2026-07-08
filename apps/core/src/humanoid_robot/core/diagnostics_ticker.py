"""Periodic system-diagnostics event pump."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from humanoid_robot.core.diagnostics import (
    GpuStats,
    HostDiagnostics,
    collect_gpu,
    collect_host,
)
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import SystemDiagnosticsTick
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort

_LOG = get_logger("cortex-core.diagnostics_ticker")


class DiagnosticsTicker:
    """Publishes `system.diagnostics.tick` on a fixed interval."""

    def __init__(
        self,
        *,
        bus: EventBusPort,
        interval_s: float = 5.0,
        host_source: Callable[[], HostDiagnostics] = collect_host,
        gpu_source: Callable[[], GpuStats] = collect_gpu,
        producer: str = "cortex-core",
    ) -> None:
        self._bus = bus
        self._interval_s = interval_s
        self._host_source = host_source
        self._gpu_source = gpu_source
        self._producer = producer
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="diagnostics-ticker")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def tick_once(self) -> None:
        """Emit a single tick — exposed for tests."""
        host = self._host_source()
        gpu = self._gpu_source()
        event = SystemDiagnosticsTick(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer=self._producer,
            ),
            host=host.model_dump(mode="json"),
            gpu=gpu.model_dump(mode="json"),
        )
        await self._bus.publish(event)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick_once()
            except Exception as exc:
                _LOG.warning("diagnostics_ticker.tick_failed", error=str(exc))
            await asyncio.sleep(self._interval_s)
