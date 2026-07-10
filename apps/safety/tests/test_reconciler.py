"""CommandReconciler tests."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.robot import MoveOutcome, RobotCommandResult
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    RobotCommandResulted,
    SafetyCommandForwarded,
    SafetyCommandTimeout,
    SafetyEStopEngaged,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import (
    ChainPolicy,
    CommandReconciler,
    EStopPolicy,
    EStopState,
    SafetyGate,
)
from humanoid_robot.testing import InMemoryEventBus


def _forwarded(command_id: str = "cmd-1") -> SafetyCommandForwarded:
    return SafetyCommandForwarded(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id=command_id,
        capability="locomotion.move",
        payload={},
    )


def _resulted(command_id: str = "cmd-1") -> RobotCommandResulted:
    return RobotCommandResulted(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id=command_id,
        result=RobotCommandResult(outcome=MoveOutcome.ACCEPTED),
    )


@pytest.mark.asyncio
async def test_result_before_timeout_leaves_estop_alone() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    reconciler = CommandReconciler(gate=gate, bus=bus, timeout_s=0.2, check_interval_s=0.02)
    await reconciler.start()

    await bus.publish(_forwarded())
    await asyncio.sleep(0.02)
    assert reconciler.pending_count() == 1
    await bus.publish(_resulted())
    await asyncio.sleep(0.05)
    assert reconciler.pending_count() == 0

    await asyncio.sleep(0.3)  # blow past timeout — nothing pending
    assert await estop.engaged() is False
    assert not any(isinstance(ev, SafetyCommandTimeout) for ev in bus.published)

    await reconciler.stop()


@pytest.mark.asyncio
async def test_timeout_engages_estop_and_emits_timeout_event() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    reconciler = CommandReconciler(gate=gate, bus=bus, timeout_s=0.05, check_interval_s=0.02)
    await reconciler.start()

    await bus.publish(_forwarded("cmd-hang"))
    await asyncio.sleep(0.2)

    assert await estop.engaged() is True
    timeouts = [ev for ev in bus.published if isinstance(ev, SafetyCommandTimeout)]
    assert len(timeouts) == 1
    assert timeouts[0].command_id == "cmd-hang"
    assert timeouts[0].elapsed_s >= 0.05

    engagements = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert any(ev.actor == "reconciler" for ev in engagements)

    await reconciler.stop()


@pytest.mark.asyncio
async def test_late_result_after_timeout_is_harmless() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    reconciler = CommandReconciler(gate=gate, bus=bus, timeout_s=0.05, check_interval_s=0.02)
    await reconciler.start()

    await bus.publish(_forwarded("cmd-late"))
    await asyncio.sleep(0.2)
    await bus.publish(_resulted("cmd-late"))  # late arrival
    await asyncio.sleep(0.05)

    assert reconciler.pending_count() == 0
    timeouts = [ev for ev in bus.published if isinstance(ev, SafetyCommandTimeout)]
    assert len(timeouts) == 1

    await reconciler.stop()
