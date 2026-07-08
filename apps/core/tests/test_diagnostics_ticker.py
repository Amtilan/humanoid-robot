"""DiagnosticsTicker publishes SystemDiagnosticsTick to the bus."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.core.diagnostics import (
    CpuStats,
    DiskStats,
    GpuStats,
    HostDiagnostics,
    MemoryStats,
)
from humanoid_robot.core.diagnostics_ticker import DiagnosticsTicker
from humanoid_robot.events import SystemDiagnosticsTick
from humanoid_robot.testing import InMemoryEventBus


def _host() -> HostDiagnostics:
    return HostDiagnostics(
        uptime_s=1.0,
        cpu=CpuStats(
            percent=1.0,
            per_core_percent=[1.0],
            load_avg_1m=0.0,
            load_avg_5m=0.0,
            load_avg_15m=0.0,
            core_count=1,
        ),
        memory=MemoryStats(
            total_bytes=1,
            used_bytes=1,
            available_bytes=0,
            percent=1.0,
            swap_total_bytes=0,
            swap_used_bytes=0,
        ),
        disks=[DiskStats(path="/", total_bytes=1, used_bytes=1, free_bytes=0, percent=100.0)],
    )


def _gpu() -> GpuStats:
    return GpuStats(supported=False, detail="test stub")


@pytest.mark.asyncio
async def test_tick_once_publishes_event() -> None:
    bus = InMemoryEventBus()
    ticker = DiagnosticsTicker(bus=bus, interval_s=60.0, host_source=_host, gpu_source=_gpu)

    await ticker.tick_once()

    events = [ev for ev in bus.published if isinstance(ev, SystemDiagnosticsTick)]
    assert len(events) == 1
    assert events[0].gpu["supported"] is False


@pytest.mark.asyncio
async def test_run_loop_stops_cleanly() -> None:
    bus = InMemoryEventBus()
    ticker = DiagnosticsTicker(bus=bus, interval_s=0.01, host_source=_host, gpu_source=_gpu)

    await ticker.start()
    await asyncio.sleep(0.05)
    await ticker.stop()

    events = [ev for ev in bus.published if isinstance(ev, SystemDiagnosticsTick)]
    assert len(events) >= 1
