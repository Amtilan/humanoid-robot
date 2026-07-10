"""End-to-end: safety.command.forwarded → UnitreeG1 (fake SDK) → result."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.unitree_g1 import UnitreeG1Adapter
from humanoid_robot.domain.robot import MoveOutcome
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotCommandResulted, SafetyCommandForwarded
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.robot_adapter_app.dispatcher import CommandDispatcher
from humanoid_robot.robot_adapter_app.runner import _resolve_arm, _resolve_locomotion
from humanoid_robot.testing import InMemoryEventBus


@dataclass(slots=True)
class _FakeLocoClient:
    move_calls: list[tuple[float, float, float, float]] = field(default_factory=list)
    stop_calls: int = 0

    def Init(self) -> None:  # noqa: N802
        return None

    def SetTimeout(self, _s: float) -> None:  # noqa: N802
        return None

    def Move(self, vx: float, vy: float, omega: float, duration: float) -> int:  # noqa: N802
        self.move_calls.append((vx, vy, omega, duration))
        return 0

    def StopMove(self) -> int:  # noqa: N802
        self.stop_calls += 1
        return 0


def _forward(capability: str, payload: dict[str, object]) -> SafetyCommandForwarded:
    return SafetyCommandForwarded(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        command_id=f"cmd-{capability}",
        capability=capability,
        payload=payload,
        submitter="test",
    )


async def _wait_for(check: object, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        await asyncio.sleep(0.01)
        if check():  # type: ignore[operator]
            return
    msg = "timed out"
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_resolver_finds_g1_locomotion_sub_adapter() -> None:
    adapter = UnitreeG1Adapter()
    loco = _resolve_locomotion(adapter)
    assert loco is not None
    assert loco is adapter.locomotion


@pytest.mark.asyncio
async def test_dispatcher_drives_g1_move_end_to_end() -> None:
    bus = InMemoryEventBus()
    adapter = UnitreeG1Adapter()
    fake_client = _FakeLocoClient()
    adapter.attach_locomotion_client(fake_client)

    dispatcher = CommandDispatcher(bus=bus)
    loco = _resolve_locomotion(adapter)
    assert loco is not None
    dispatcher.register_locomotion(loco)
    await dispatcher.start()

    await bus.publish(
        _forward(
            "locomotion.move",
            {
                "linear_x_mps": 0.4,
                "linear_y_mps": 0.0,
                "angular_z_rps": 0.2,
                "duration_ms": 600,
            },
        )
    )
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.ACCEPTED
    assert fake_client.move_calls == [(0.4, 0.0, 0.2, 0.6)]

    await dispatcher.stop()


@dataclass(slots=True)
class _FakeArmClient:
    executed: list[int] = field(default_factory=list)

    def SetTimeout(self, _t: float) -> None:  # noqa: N802
        return None

    def Init(self) -> None:  # noqa: N802
        return None

    def ExecuteAction(self, action_id: int) -> int:  # noqa: N802
        self.executed.append(action_id)
        return 0


@pytest.mark.asyncio
async def test_dispatcher_drives_g1_arm_gesture_end_to_end() -> None:
    bus = InMemoryEventBus()
    adapter = UnitreeG1Adapter()
    fake_arm = _FakeArmClient()
    adapter.attach_arm_client(fake_arm, action_map={"high wave": 22, "release arm": 99})

    dispatcher = CommandDispatcher(bus=bus)
    arm = _resolve_arm(adapter)
    assert arm is not None
    dispatcher.register_arm(arm)
    await dispatcher.start()

    await bus.publish(_forward("arms.gesture", {"gesture": "high wave"}))
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.ACCEPTED
    assert fake_arm.executed == [22]

    await dispatcher.stop()


@pytest.mark.asyncio
async def test_dispatcher_arm_missing_gesture_field_rejected() -> None:
    bus = InMemoryEventBus()
    adapter = UnitreeG1Adapter()
    adapter.attach_arm_client(_FakeArmClient(), action_map={"high wave": 22})

    dispatcher = CommandDispatcher(bus=bus)
    arm = _resolve_arm(adapter)
    assert arm is not None
    dispatcher.register_arm(arm)
    await dispatcher.start()

    await bus.publish(_forward("arms.gesture", {}))  # missing 'gesture'
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.REJECTED_BY_POLICY
    assert result.result.error_code == "missing_gesture"

    await dispatcher.stop()


@pytest.mark.asyncio
async def test_dispatcher_drives_g1_stop_without_lifecycle_collision() -> None:
    """Regression: earlier the dispatcher routed StopCommand into the
    adapter's lifecycle `stop()` because the root Protocol-matched
    LocomotionPort by name. Now sub-adapter isolates the two."""
    bus = InMemoryEventBus()
    adapter = UnitreeG1Adapter()
    fake_client = _FakeLocoClient()
    adapter.attach_locomotion_client(fake_client)

    dispatcher = CommandDispatcher(bus=bus)
    loco = _resolve_locomotion(adapter)
    assert loco is not None
    dispatcher.register_locomotion(loco)
    await dispatcher.start()

    await bus.publish(_forward("locomotion.stop", {"reason": "operator_requested"}))
    await _wait_for(lambda: any(isinstance(ev, RobotCommandResulted) for ev in bus.published))

    result = next(ev for ev in bus.published if isinstance(ev, RobotCommandResulted))
    assert result.result.outcome == MoveOutcome.ACCEPTED
    assert fake_client.stop_calls == 1

    await dispatcher.stop()
