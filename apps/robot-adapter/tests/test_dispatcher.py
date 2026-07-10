"""CommandDispatcher tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from humanoid_robot.domain.robot import MoveOutcome
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotCommandResulted, SafetyCommandForwarded
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.robot_adapter_app.dispatcher import CommandDispatcher
from humanoid_robot.testing import InMemoryEventBus, MockRobotAdapter


def _forward(capability: str, payload: dict[str, object]) -> SafetyCommandForwarded:
    return SafetyCommandForwarded(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id="cmd-1",
        capability=capability,
        payload=payload,
    )


async def _wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        await asyncio.sleep(0.01)
        if condition():
            return
    msg = "timed out"
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_dispatcher_forwards_move_to_locomotion() -> None:
    bus = InMemoryEventBus()
    adapter = MockRobotAdapter()
    dispatcher = CommandDispatcher(bus=bus)
    dispatcher.register_locomotion(adapter.locomotion)
    await dispatcher.start()

    await bus.publish(
        _forward(
            "locomotion.move",
            {
                "linear_x_mps": 0.3,
                "linear_y_mps": 0.0,
                "angular_z_rps": 0.0,
                "duration_ms": 500,
            },
        )
    )
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.ACCEPTED
    assert len(adapter.moves) == 1
    assert adapter.moves[0].linear_x_mps == 0.3

    await dispatcher.stop()


@pytest.mark.asyncio
async def test_unhandled_capability_rejects_by_policy() -> None:
    bus = InMemoryEventBus()
    dispatcher = CommandDispatcher(bus=bus)
    await dispatcher.start()

    await bus.publish(_forward("head.pose", {"pitch": 0.0}))
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.REJECTED_BY_POLICY
    assert result.result.error_code == "capability_unsupported"

    await dispatcher.stop()


@pytest.mark.asyncio
async def test_handler_exception_becomes_hardware_error() -> None:
    async def _boom(_payload: dict[str, object]) -> object:
        msg = "sensor timeout"
        raise RuntimeError(msg)

    bus = InMemoryEventBus()
    dispatcher = CommandDispatcher(bus=bus)
    dispatcher.register("locomotion.move", _boom)  # type: ignore[arg-type]
    await dispatcher.start()

    await bus.publish(
        _forward(
            "locomotion.move", {"linear_x_mps": 0.0, "linear_y_mps": 0.0, "angular_z_rps": 0.0}
        )
    )
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.HARDWARE_ERROR
    assert result.result.error_code == "RuntimeError"
    assert "sensor timeout" in (result.result.error_message or "")

    await dispatcher.stop()
