"""MockRobotAdapter — a programmable robot for tests.

Constructor accepts a `RobotManifest`. All command invocations are recorded
via the `.locomotion` sub-adapter for assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from humanoid_robot.domain.robot import (
    MoveCommand,
    MoveOutcome,
    RobotCapabilities,
    RobotCommandResult,
    RobotManifest,
    RobotModel,
    StopCommand,
)


@dataclass(slots=True)
class MockLocomotion:
    """A LocomotionPort that just records what it was asked to do."""

    _moves: list[MoveCommand] = field(default_factory=list)
    _stops: list[StopCommand] = field(default_factory=list)

    async def move(self, cmd: MoveCommand) -> RobotCommandResult:
        self._moves.append(cmd)
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    async def stop(self, cmd: StopCommand) -> RobotCommandResult:
        self._stops.append(cmd)
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    @property
    def moves(self) -> list[MoveCommand]:
        return list(self._moves)

    @property
    def stops(self) -> list[StopCommand]:
        return list(self._stops)


@dataclass(slots=True)
class MockRobotAdapter:
    """A robot whose responses are entirely under test control."""

    manifest: RobotManifest = field(
        default_factory=lambda: RobotManifest(
            adapter_name="mock",
            adapter_version="0.0.0",
            robot_model=RobotModel(vendor="mock", family="mock", variant="mock"),
            capabilities=RobotCapabilities(),
        )
    )
    locomotion: MockLocomotion = field(default_factory=MockLocomotion)
    _started: bool = False

    @property
    def capabilities(self) -> RobotCapabilities:
        return self.manifest.capabilities

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    # ---- assertion helpers ---------------------------------------------------

    @property
    def moves(self) -> list[MoveCommand]:
        return self.locomotion.moves

    @property
    def stops(self) -> list[StopCommand]:
        return self.locomotion.stops

    @property
    def is_started(self) -> bool:
        return self._started
