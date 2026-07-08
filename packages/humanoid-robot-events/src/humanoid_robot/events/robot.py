"""Robot lifecycle and control events."""

from __future__ import annotations

from typing import Any, ClassVar

from humanoid_robot.domain.robot import (
    RobotCapabilities,
    RobotCommandResult,
    RobotModel,
)
from humanoid_robot.events.base import BaseEvent


class RobotAdapterReady(BaseEvent):
    """A robot adapter finished startup and is exposing its ports."""

    subject: ClassVar[str] = "robot.adapter.ready"
    schema_version: ClassVar[int] = 1

    adapter_name: str
    adapter_version: str
    robot_model: RobotModel
    capabilities: RobotCapabilities


class RobotCommandRequested(BaseEvent):
    """A command was requested on the robot adapter."""

    subject: ClassVar[str] = "robot.command.requested"
    schema_version: ClassVar[int] = 1

    command_id: str
    capability: str  # e.g. "locomotion.move", "arms.gesture"
    payload: dict[str, Any]


class RobotCommandResulted(BaseEvent):
    """A robot command reached a terminal state."""

    subject: ClassVar[str] = "robot.command.result"
    schema_version: ClassVar[int] = 1

    command_id: str
    result: RobotCommandResult


class RobotTelemetry(BaseEvent):
    """Periodic telemetry sample from the robot adapter."""

    subject: ClassVar[str] = "robot.telemetry"
    schema_version: ClassVar[int] = 1

    kind: str  # e.g. "battery", "imu", "temperature"
    payload: dict[str, Any]
