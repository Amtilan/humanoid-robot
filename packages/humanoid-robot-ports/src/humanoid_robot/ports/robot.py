"""Robot capability ports.

An adapter implements only the ports its robot actually supports — missing
capabilities are represented by absence, not by no-op implementations. The
absence is discoverable through `RobotAdapterPort.capabilities`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.robot import (
    HeadPoseCommand,
    MoveCommand,
    PostureCommand,
    RobotCapabilities,
    RobotCommandResult,
    RobotManifest,
    StopCommand,
)
from humanoid_robot.domain.voice import AudioFormat


class AudioFrame(BaseModel):
    """One frame of raw PCM audio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pcm: bytes
    format: AudioFormat
    monotonic_ns: int = Field(ge=0)


@runtime_checkable
class RobotAdapterPort(Protocol):
    """Root port for a robot adapter.

    The adapter reports what it can do (`capabilities`) and gives concrete
    per-capability ports on demand.
    """

    @property
    def manifest(self) -> RobotManifest: ...

    @property
    def capabilities(self) -> RobotCapabilities: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@runtime_checkable
class LocomotionPort(Protocol):
    """Sends body-frame velocity commands to the robot base."""

    async def move(self, cmd: MoveCommand) -> RobotCommandResult: ...

    async def stop(self, cmd: StopCommand) -> RobotCommandResult: ...


@runtime_checkable
class ArmPort(Protocol):
    """Executes named arm gestures on a single arm."""

    async def perform_gesture(self, gesture: str) -> RobotCommandResult: ...

    async def release(self) -> RobotCommandResult: ...

    def supported_gestures(self) -> tuple[str, ...]: ...


@runtime_checkable
class HandPort(Protocol):
    """Controls a dexterous hand (grip open/close, per-finger positions)."""

    async def open(self) -> RobotCommandResult: ...

    async def close(self) -> RobotCommandResult: ...

    async def set_positions(self, positions: tuple[float, ...]) -> RobotCommandResult: ...


@runtime_checkable
class PosturePort(Protocol):
    """Whole-body posture / locomotion-FSM transitions (damp, stand, …)."""

    async def set_posture(self, cmd: PostureCommand) -> RobotCommandResult: ...


@runtime_checkable
class HeadPort(Protocol):
    """Orients the robot's head to an absolute (pitch, yaw) pose."""

    async def set_pose(self, cmd: HeadPoseCommand) -> RobotCommandResult: ...

    async def reset(self) -> RobotCommandResult: ...


@runtime_checkable
class BatteryPort(Protocol):
    """Reads battery telemetry (percentage 0.0-1.0)."""

    async def read_percentage(self) -> float: ...


@runtime_checkable
class AudioInPort(Protocol):
    """Streams microphone audio as `AudioFrame`s."""

    def stream(self) -> AsyncIterator[AudioFrame]: ...

    async def close(self) -> None: ...


@runtime_checkable
class AudioOutPort(Protocol):
    """Plays PCM audio through the robot's speaker."""

    async def play(self, frame: AudioFrame) -> None: ...

    async def flush(self) -> None: ...

    async def stop(self) -> None: ...
