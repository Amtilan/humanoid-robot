"""SafetyWatchdog tests."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import SafetyEStopEngaged, SafetyWatchdogHeartbeat
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    SafetyGate,
    SafetyWatchdog,
)
from humanoid_robot.testing import InMemoryEventBus


def _heartbeat(actor: str = "operator") -> SafetyWatchdogHeartbeat:
    return SafetyWatchdogHeartbeat(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        actor=actor,
    )


@pytest.mark.asyncio
async def test_watchdog_engages_after_timeout() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    watchdog = SafetyWatchdog(gate=gate, bus=bus, timeout_s=0.05, check_interval_s=0.02)

    await watchdog.start()
    await bus.publish(_heartbeat())
    await asyncio.sleep(0.03)
    assert await watchdog.is_live() is True

    # Stop heartbeats; wait past timeout + one check.
    await asyncio.sleep(0.15)

    assert await estop.engaged() is True
    engagement_events = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert any(ev.actor == "watchdog" for ev in engagement_events)

    await watchdog.stop()


@pytest.mark.asyncio
async def test_watchdog_no_engagement_before_first_heartbeat() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    watchdog = SafetyWatchdog(gate=gate, bus=bus, timeout_s=0.02, check_interval_s=0.02)

    await watchdog.start()
    await asyncio.sleep(0.1)
    assert await estop.engaged() is False  # never went live → nothing to trip

    await watchdog.stop()


@pytest.mark.asyncio
async def test_watchdog_only_engages_once_across_reengagement_window() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(policy=ChainPolicy([EStopPolicy(estop)]), bus=bus, estop=estop)
    watchdog = SafetyWatchdog(gate=gate, bus=bus, timeout_s=0.05, check_interval_s=0.02)

    await watchdog.start()
    await bus.publish(_heartbeat())
    await asyncio.sleep(0.15)  # expire
    await asyncio.sleep(0.1)  # more idle ticks — must NOT emit further engagements

    engagement_events = [ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged)]
    assert len(engagement_events) == 1

    await watchdog.stop()
