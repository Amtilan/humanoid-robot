"""TelemetryPump tests."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.adapters.unitree_g1.battery import UnitreeG1Battery
from humanoid_robot.events import RobotTelemetry
from humanoid_robot.robot_adapter_app.telemetry_pump import (
    TelemetryPump,
    battery_source,
)
from humanoid_robot.testing import InMemoryEventBus


@pytest.mark.asyncio
async def test_battery_source_publishes_percentage() -> None:
    bus = InMemoryEventBus()
    battery = UnitreeG1Battery(source=lambda: 0.72)
    pump = TelemetryPump(bus=bus, interval_s=0.02)
    pump.register(battery_source(battery))
    await pump.start()

    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(isinstance(ev, RobotTelemetry) for ev in bus.published):
            break

    telemetry = next(ev for ev in bus.published if isinstance(ev, RobotTelemetry))
    assert telemetry.kind == "battery"
    assert telemetry.payload["percentage"] == pytest.approx(0.72)

    await pump.stop()


@pytest.mark.asyncio
async def test_source_failure_is_swallowed_and_pump_lives() -> None:
    bus = InMemoryEventBus()

    async def _boom() -> None:
        msg = "hardware brown-out"
        raise RuntimeError(msg)

    pump = TelemetryPump(bus=bus, interval_s=0.02)
    pump.register(_boom)  # type: ignore[arg-type]

    battery = UnitreeG1Battery(source=lambda: 0.5)
    pump.register(battery_source(battery))
    await pump.start()

    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(isinstance(ev, RobotTelemetry) for ev in bus.published):
            break

    telemetry = next(ev for ev in bus.published if isinstance(ev, RobotTelemetry))
    assert telemetry.payload["percentage"] == pytest.approx(0.5)

    await pump.stop()


@pytest.mark.asyncio
async def test_battery_clamps_out_of_range_values() -> None:
    battery = UnitreeG1Battery(source=lambda: 1.7)
    value = await battery.read_percentage()
    assert value == 1.0

    battery_low = UnitreeG1Battery(source=lambda: -0.2)
    assert await battery_low.read_percentage() == 0.0
