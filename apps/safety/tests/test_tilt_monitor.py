"""TiltMonitor tests."""

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
    SafetyGate,
    TiltMonitor,
)
from humanoid_robot.testing import InMemoryEventBus


def _imu(payload: dict[str, float]) -> RobotTelemetry:
    return RobotTelemetry(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        kind="imu",
        payload=dict(payload),
    )


def _other_kind() -> RobotTelemetry:
    return RobotTelemetry(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        kind="battery",
        payload={"percentage": 0.5},
    )


@pytest.mark.asyncio
async def test_tilt_within_limit_does_nothing() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = TiltMonitor(gate=gate, bus=bus, max_pitch_rad=0.5, max_roll_rad=0.5)
    await monitor.start()

    await bus.publish(_imu({"pitch_rad": 0.1, "roll_rad": 0.2}))
    await asyncio.sleep(0.02)

    assert await estop.engaged() is False
    assert not any(isinstance(ev, SafetyEStopEngaged) for ev in bus.published)

    await monitor.stop()


@pytest.mark.asyncio
async def test_pitch_over_limit_engages_estop() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = TiltMonitor(gate=gate, bus=bus, max_pitch_rad=0.5, max_roll_rad=0.5)
    await monitor.start()

    # Enter safe state first so we can observe the transition edge.
    await bus.publish(_imu({"pitch_rad": 0.1, "roll_rad": 0.0}))
    await asyncio.sleep(0.01)
    await bus.publish(_imu({"pitch_rad": 1.2, "roll_rad": 0.0}))
    await asyncio.sleep(0.05)

    assert await estop.engaged() is True
    engaged = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert any(ev.actor == "tilt-monitor" for ev in engaged)
    assert "pitch" in engaged[0].reason

    await monitor.stop()


@pytest.mark.asyncio
async def test_only_engages_once_on_repeated_bad_samples() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = TiltMonitor(gate=gate, bus=bus, max_pitch_rad=0.3, max_roll_rad=0.3)
    await monitor.start()

    await bus.publish(_imu({"pitch_rad": 0.1, "roll_rad": 0.0}))
    await asyncio.sleep(0.01)
    for _ in range(3):
        await bus.publish(_imu({"pitch_rad": 0.9, "roll_rad": 0.0}))
        await asyncio.sleep(0.01)

    engaged = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert len(engaged) == 1

    await monitor.stop()


@pytest.mark.asyncio
async def test_non_imu_telemetry_ignored() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = TiltMonitor(gate=gate, bus=bus)
    await monitor.start()

    await bus.publish(_other_kind())
    await asyncio.sleep(0.02)
    assert await estop.engaged() is False

    await monitor.stop()


@pytest.mark.asyncio
async def test_missing_pitch_roll_keys_ignored() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    monitor = TiltMonitor(gate=gate, bus=bus, max_pitch_rad=0.1, max_roll_rad=0.1)
    await monitor.start()

    await bus.publish(_imu({"gyro_x": 0.5}))
    await asyncio.sleep(0.02)
    assert await estop.engaged() is False

    await monitor.stop()
