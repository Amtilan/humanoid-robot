"""Robot bounded context — hardware-agnostic capability model."""

from humanoid_robot.domain.robot.capabilities import (
    ArmCapability,
    AudioCapability,
    BatteryCapability,
    CameraCapability,
    HandCapability,
    HeadCapability,
    LocomotionCapability,
    LocomotionKind,
    RobotCapabilities,
    RobotManifest,
    RobotModel,
)
from humanoid_robot.domain.robot.commands import (
    HeadPoseCommand,
    MoveCommand,
    MoveOutcome,
    PostureCommand,
    PostureKind,
    RobotCommandResult,
    StopCommand,
)

__all__ = [
    "ArmCapability",
    "AudioCapability",
    "BatteryCapability",
    "CameraCapability",
    "HandCapability",
    "HeadCapability",
    "HeadPoseCommand",
    "LocomotionCapability",
    "LocomotionKind",
    "MoveCommand",
    "MoveOutcome",
    "PostureCommand",
    "PostureKind",
    "RobotCapabilities",
    "RobotCommandResult",
    "RobotManifest",
    "RobotModel",
    "StopCommand",
]
