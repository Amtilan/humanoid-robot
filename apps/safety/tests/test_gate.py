"""SafetyGate integration tests over InMemoryEventBus."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    RobotCommandRequested,
    SafetyCommandDenied,
    SafetyCommandForwarded,
    SafetyEStopEngaged,
    SafetyEStopReleased,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.ports import SafetyDecision, SafetyRequest
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    SafetyGate,
)
from humanoid_robot.testing import InMemoryEventBus


def _command(capability: str = "locomotion.move") -> RobotCommandRequested:
    return RobotCommandRequested(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id="cmd-1",
        capability=capability,
        payload={"velocity": 0.4},
    )


async def _wait_for(condition: Any, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        await asyncio.sleep(0.01)
        if condition():
            return
    msg = "condition timed out"
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_gate_denies_while_estop_engaged() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=True)
    policy = ChainPolicy(
        [
            KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
            EStopPolicy(estop),
        ]
    )
    gate = SafetyGate(policy=policy, bus=bus, estop=estop)
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    await bus.publish(_command())
    await _wait_for(lambda: any(isinstance(ev, SafetyCommandDenied) for ev in bus.published))

    denial = next(ev for ev in bus.published if isinstance(ev, SafetyCommandDenied))
    assert "e-stop" in denial.reason.lower()

    gate.request_stop()
    await run


@pytest.mark.asyncio
async def test_gate_forwards_when_released_and_allowlisted() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    policy = ChainPolicy(
        [
            KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
            EStopPolicy(estop),
        ]
    )
    gate = SafetyGate(policy=policy, bus=bus, estop=estop)
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    await bus.publish(_command())
    await _wait_for(lambda: any(isinstance(ev, SafetyCommandForwarded) for ev in bus.published))

    gate.request_stop()
    await run


@pytest.mark.asyncio
async def test_engage_release_emits_events() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(
        policy=ChainPolicy([EStopPolicy(estop)]),
        bus=bus,
        estop=estop,
    )

    assert await gate.engage_estop(actor="operator", reason="test") is True
    assert await gate.engage_estop(actor="operator") is False  # idempotent
    assert await gate.release_estop(actor="operator") is True
    assert await gate.release_estop(actor="operator") is False  # idempotent

    kinds = [type(ev).__name__ for ev in bus.published]
    assert kinds.count("SafetyEStopEngaged") == 1
    assert kinds.count("SafetyEStopReleased") == 1

    engaged = next(ev for ev in bus.published if isinstance(ev, SafetyEStopEngaged))
    assert engaged.actor == "operator"
    assert engaged.reason == "test"
    released = next(ev for ev in bus.published if isinstance(ev, SafetyEStopReleased))
    assert released.actor == "operator"


@pytest.mark.asyncio
async def test_policy_exception_fails_closed() -> None:
    class _Boom:
        async def evaluate(self, _req: SafetyRequest) -> SafetyDecision:
            raise RuntimeError("bang")

    bus = InMemoryEventBus()
    gate = SafetyGate(policy=_Boom(), bus=bus, estop=EStopState(engaged=False))
    run = asyncio.create_task(gate.run())
    await asyncio.sleep(0)

    await bus.publish(_command())
    await _wait_for(lambda: any(isinstance(ev, SafetyCommandDenied) for ev in bus.published))

    denial = next(ev for ev in bus.published if isinstance(ev, SafetyCommandDenied))
    assert "policy_error" in denial.reason

    gate.request_stop()
    await run
