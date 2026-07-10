"""UnitreeG1Head tests with an injected fake LocoClient."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from humanoid_robot.adapters.unitree_g1.adapter import UnitreeG1Adapter
from humanoid_robot.adapters.unitree_g1.head import (
    UnitreeG1Head,
    UnitreeHeadUnavailableError,
)
from humanoid_robot.domain.robot import HeadPoseCommand, MoveOutcome


@dataclass(slots=True)
class _FakeLocoClient:
    pose_calls: list[tuple[float, float]] = field(default_factory=list)
    pose_return: int = 0
    pose_raises: BaseException | None = None

    def Init(self) -> None:  # noqa: N802
        return None

    def SetTimeout(self, _s: float) -> None:  # noqa: N802
        return None

    def SetHeadPose(self, pitch: float, yaw: float) -> int:  # noqa: N802
        if self.pose_raises is not None:
            raise self.pose_raises
        self.pose_calls.append((pitch, yaw))
        return self.pose_return


class TestHead:
    async def test_set_pose_forwards_pitch_yaw(self) -> None:
        client = _FakeLocoClient()
        head = UnitreeG1Head(client=client)
        result = await head.set_pose(HeadPoseCommand(pitch_rad=0.2, yaw_rad=-0.3, duration_ms=300))
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.pose_calls == [(0.2, -0.3)]

    async def test_hardware_error_returns_typed_result(self) -> None:
        client = _FakeLocoClient(pose_raises=RuntimeError("torque limit"))
        head = UnitreeG1Head(client=client)
        result = await head.set_pose(HeadPoseCommand(pitch_rad=0.1, yaw_rad=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "RuntimeError"
        assert "torque limit" in (result.error_message or "")

    async def test_non_zero_return_code_is_hardware_error(self) -> None:
        client = _FakeLocoClient(pose_return=5)
        head = UnitreeG1Head(client=client)
        result = await head.set_pose(HeadPoseCommand(pitch_rad=0.0, yaw_rad=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "loco_client_error"

    async def test_reset_sends_zeros(self) -> None:
        client = _FakeLocoClient()
        head = UnitreeG1Head(client=client)
        result = await head.reset()
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.pose_calls == [(0.0, 0.0)]

    async def test_missing_sdk_reports_sdk_unavailable(self) -> None:
        head = UnitreeG1Head()
        result = await head.set_pose(HeadPoseCommand(pitch_rad=0.0, yaw_rad=0.0))
        assert result.outcome == MoveOutcome.HARDWARE_ERROR
        assert result.error_code == "sdk_unavailable"


class TestAdapterIntegration:
    async def test_attach_head_client_lets_adapter_orient(self) -> None:
        client = _FakeLocoClient()
        adapter = UnitreeG1Adapter()
        adapter.attach_head_client(client)

        result = await adapter.head.set_pose(
            HeadPoseCommand(pitch_rad=0.15, yaw_rad=0.4, duration_ms=200)
        )
        assert result.outcome == MoveOutcome.ACCEPTED
        assert client.pose_calls == [(0.15, 0.4)]


class TestUnavailable:
    def test_error_message_mentions_head_pose(self) -> None:
        with pytest.raises(UnitreeHeadUnavailableError, match="head-pose"):
            raise UnitreeHeadUnavailableError
