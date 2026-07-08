"""MockRobotAdapter — a programmable robot for tests.

Constructor accepts a `RobotManifest` and per-command handlers. All command
invocations are recorded for assertions.
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
    _moves: list[MoveCommand] = field(default_factory=list)
    _stops: list[StopCommand] = field(default_factory=list)
    _started: bool = False

    @property
    def capabilities(self) -> RobotCapabilities:
        return self.manifest.capabilities

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def move(self, cmd: MoveCommand) -> RobotCommandResult:
        self._moves.append(cmd)
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    async def emergency_stop(self, cmd: StopCommand) -> RobotCommandResult:
        self._stops.append(cmd)
        return RobotCommandResult(outcome=MoveOutcome.ACCEPTED)

    # ---- assertion helpers ---------------------------------------------------

    @property
    def moves(self) -> list[MoveCommand]:
        return list(self._moves)

    @property
    def stops(self) -> list[StopCommand]:
        return list(self._stops)

    @property
    def is_started(self) -> bool:
        return self._started
