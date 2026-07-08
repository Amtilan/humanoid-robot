"""UnitreeG1Arm tests using an injected fake SDK — no vendor deps."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from humanoid_robot.adapters.unitree_g1.arm import UnitreeG1Arm
from humanoid_robot.adapters.unitree_g1.sdk import SdkHandles
from humanoid_robot.domain.robot import MoveOutcome


@dataclass(slots=True)
class _FakeArmClient:
    executed: list[int] = field(default_factory=list)
    next_return_code: int = 0
    _timeout: float = 0.0
    _init_calls: int = 0

    def SetTimeout(self, t: float) -> None:
        self._timeout = t

    def Init(self) -> None:
        self._init_calls += 1

    def ExecuteAction(self, action_id: int) -> int:
        self.executed.append(action_id)
        return self.next_return_code


def _mk_handles(actions: dict[str, int] | None = None) -> tuple[SdkHandles, _FakeArmClient]:
    actions = actions or {"high wave": 1, "release arm": 99}
    fake_client = _FakeArmClient()
    arm_module = SimpleNamespace(
        G1ArmActionClient=lambda: fake_client,
        action_map=actions,
    )
    handles = SdkHandles(
        channel=SimpleNamespace(),
        audio_client=SimpleNamespace(),
        arm_client=arm_module,
        loco_client=None,
    )
    return handles, fake_client


class TestUnitreeG1Arm:
    async def test_perform_known_gesture_calls_execute_action(self) -> None:
        handles, fake = _mk_handles()
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        result = await arm.perform_gesture("high wave")
        assert result.outcome == MoveOutcome.ACCEPTED
        assert fake.executed == [1]

    async def test_unknown_gesture_rejected_by_policy(self) -> None:
        handles, fake = _mk_handles()
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        result = await arm.perform_gesture("moonwalk")
        assert result.outcome == MoveOutcome.REJECTED_BY_POLICY
        assert result.error_code == "UNKNOWN_GESTURE"
        assert fake.executed == []

    async def test_nonzero_rc_reported_as_hardware_error(self) -> None:
        handles, fake = _mk_handles()
        fake.next_return_code = 42
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        result = await arm.perform_gesture("high wave")
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "42"

    async def test_release_uses_release_arm_action(self) -> None:
        handles, fake = _mk_handles()
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        await arm.release()
        assert fake.executed == [99]

    def test_supported_gestures_reads_action_map(self) -> None:
        handles, _ = _mk_handles({"a": 1, "b": 2})
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        assert set(arm.supported_gestures()) == {"a", "b"}

    async def test_client_initialised_once(self) -> None:
        handles, fake = _mk_handles()
        arm = UnitreeG1Arm(arm_id="right", _sdk=handles)
        await arm.perform_gesture("high wave")
        await arm.perform_gesture("high wave")
        assert fake._init_calls == 1
