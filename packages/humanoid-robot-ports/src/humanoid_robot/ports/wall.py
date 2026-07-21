"""Port for driving the presentation video wall."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from humanoid_robot.domain.wall import WallCommand, WallCommandResult


@runtime_checkable
class WallControlPort(Protocol):
    """Sends control commands to the video-wall agent."""

    async def send(self, command: WallCommand) -> WallCommandResult:
        """Deliver one command; never raises, failures map to outcomes."""
        ...

    async def health(self) -> bool:
        """True when the wall agent is reachable and ready."""
        ...

    async def close(self) -> None:
        """Release underlying transport resources."""
        ...
