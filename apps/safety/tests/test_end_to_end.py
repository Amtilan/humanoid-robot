"""End-to-end: request → safety gate → dispatcher → adapter → result."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.robot import MoveOutcome
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import (
    RobotCommandRequested,
    RobotCommandResulted,
    SafetyCommandDenied,
)
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.robot_adapter_app.dispatcher import CommandDispatcher
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    SafetyGate,
    VelocityLimitPolicy,
)
from humanoid_robot.testing import InMemoryEventBus, MockRobotAdapter


def _request(capability: str, payload: dict[str, object]) -> RobotCommandRequested:
    return RobotCommandRequested(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id=f"cmd-{capability}",
        capability=capability,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_released_estop_full_loop() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    adapter = MockRobotAdapter()
    dispatcher = CommandDispatcher(bus=bus)
    dispatcher.register_locomotion(adapter)

    gate_task = asyncio.create_task(gate.run())
    await dispatcher.start()
    await asyncio.sleep(0)

    await bus.publish(
        _request(
            "locomotion.move",
            {
                "linear_x_mps": 0.4,
                "linear_y_mps": 0.0,
                "angular_z_rps": 0.0,
                "duration_ms": 300,
            },
        )
    )
    for _ in range(200):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, RobotCommandResulted) for ev in bus.published):
            break

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.ACCEPTED
    assert len(adapter.moves) == 1

    gate.request_stop()
    await gate_task
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_velocity_over_limit_denied_before_adapter() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=False)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                VelocityLimitPolicy(max_linear_speed_mps=0.5, max_angular_rate_rps=1.0),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    adapter = MockRobotAdapter()
    dispatcher = CommandDispatcher(bus=bus)
    dispatcher.register_locomotion(adapter)

    gate_task = asyncio.create_task(gate.run())
    await dispatcher.start()
    await asyncio.sleep(0)

    # 2.0 m/s — 4x limit
    await bus.publish(
        _request(
            "locomotion.move",
            {"linear_x_mps": 2.0, "linear_y_mps": 0.0, "angular_z_rps": 0.0},
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, SafetyCommandDenied) for ev in bus.published):
            break

    denied = next(ev for ev in bus.published if isinstance(ev, SafetyCommandDenied))
    assert "linear speed" in denied.reason
    assert adapter.moves == []

    gate.request_stop()
    await gate_task
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_engaged_estop_never_reaches_adapter() -> None:
    bus = InMemoryEventBus()
    estop = EStopState(engaged=True)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset({"locomotion.move"})),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    adapter = MockRobotAdapter()
    dispatcher = CommandDispatcher(bus=bus)
    dispatcher.register_locomotion(adapter)

    gate_task = asyncio.create_task(gate.run())
    await dispatcher.start()
    await asyncio.sleep(0)

    await bus.publish(
        _request(
            "locomotion.move", {"linear_x_mps": 0.4, "linear_y_mps": 0.0, "angular_z_rps": 0.0}
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(isinstance(ev, SafetyCommandDenied) for ev in bus.published):
            break

    denied = next(ev for ev in bus.published if isinstance(ev, SafetyCommandDenied))
    assert "e-stop" in denied.reason.lower()
    assert not any(isinstance(ev, RobotCommandResulted) for ev in bus.published)
    assert adapter.moves == []

    gate.request_stop()
    await gate_task
    await dispatcher.stop()
