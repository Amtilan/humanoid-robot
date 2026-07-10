"""OverheatMonitor tests."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotTelemetry, SafetyEStopEngaged
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    OverheatMonitor,
    SafetyGate,
)
from humanoid_robot.testing import InMemoryEventBus


def _temp(payload: dict[str, float]) -> RobotTelemetry:
    return RobotTelemetry(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        kind="temperature",
        payload=dict(payload),
    )


@pytest.mark.asyncio
async def test_within_limit_no_action() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = OverheatMonitor(gate=gate, bus=bus, max_temperature_c=80.0)
    await monitor.start()

    await bus.publish(_temp({"cpu": 60.0, "battery": 40.0}))
    await asyncio.sleep(0.02)
    assert await estop.engaged() is False

    await monitor.stop()


@pytest.mark.asyncio
async def test_over_limit_engages_estop() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = OverheatMonitor(gate=gate, bus=bus, max_temperature_c=80.0)
    await monitor.start()

    # Enter safe state first so we can observe the transition edge.
    await bus.publish(_temp({"cpu": 60.0}))
    await asyncio.sleep(0.02)
    await bus.publish(_temp({"cpu": 60.0, "motor_left_hip": 92.0}))
    await asyncio.sleep(0.05)

    assert await estop.engaged() is True
    engagements = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert any(ev.actor == "overheat-monitor" for ev in engagements)
    assert "motor_left_hip" in engagements[0].reason

    await monitor.stop()


@pytest.mark.asyncio
async def test_only_engages_once_across_repeated_bad_samples() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = OverheatMonitor(gate=gate, bus=bus, max_temperature_c=80.0)
    await monitor.start()

    await bus.publish(_temp({"cpu": 60.0}))
    await asyncio.sleep(0.01)
    for _ in range(3):
        await bus.publish(_temp({"cpu": 95.0}))
        await asyncio.sleep(0.01)

    engagements = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert len(engagements) == 1

    await monitor.stop()


@pytest.mark.asyncio
async def test_non_temperature_telemetry_ignored() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = OverheatMonitor(gate=gate, bus=bus, max_temperature_c=1.0)
    await monitor.start()

    await bus.publish(
        RobotTelemetry(
            meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
            kind="battery",
            payload={"percentage": 999.0},
        )
    )
    await asyncio.sleep(0.02)
    assert await estop.engaged() is False

    await monitor.stop()
