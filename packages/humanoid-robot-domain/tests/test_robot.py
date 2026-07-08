"""Robot domain tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from humanoid_robot.domain.robot import (
    AudioCapability,
    LocomotionCapability,
    LocomotionKind,
    MoveCommand,
    RobotCapabilities,
    RobotManifest,
    RobotModel,
)


class TestRobotModel:
    def test_slug_is_lowercase_underscored(self) -> None:
        m = RobotModel(vendor="Unitree", family="G1", variant="EDU")
        assert m.slug == "unitree_g1_edu"


class TestRobotManifest:
    def test_capabilities_default_empty(self) -> None:
        manifest = RobotManifest(
            adapter_name="mock",
            adapter_version="0.0.1",
            robot_model=RobotModel(vendor="mock", family="mock", variant="mock"),
            capabilities=RobotCapabilities(),
        )
        assert manifest.capabilities.arms == ()
        assert manifest.capabilities.hands == ()
        assert manifest.capabilities.locomotion is None

    def test_manifest_frozen(self) -> None:
        manifest = RobotManifest(
            adapter_name="mock",
            adapter_version="0.0.1",
            robot_model=RobotModel(vendor="m", family="m", variant="m"),
            capabilities=RobotCapabilities(
                locomotion=LocomotionCapability(
                    kind=LocomotionKind.LEGGED_BIPEDAL, max_speed_mps=1.5
                ),
                audio_in=AudioCapability(kind="alsa", channels=1, sample_rate_hz=16_000),
            ),
        )
        with pytest.raises(ValidationError):
            manifest.adapter_name = "other"  # type: ignore[misc]  # frozen model


class TestMoveCommand:
    def test_rejects_out_of_range_velocity(self) -> None:
        with pytest.raises(ValidationError):
            MoveCommand(linear_x_mps=100.0, linear_y_mps=0, angular_z_rps=0)

    def test_defaults_duration_zero(self) -> None:
        cmd = MoveCommand(linear_x_mps=0.5, linear_y_mps=0.0, angular_z_rps=0.0)
        assert cmd.duration_ms == 0
