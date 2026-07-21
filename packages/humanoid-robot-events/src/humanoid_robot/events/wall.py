"""Video-wall control events."""

from __future__ import annotations

from typing import ClassVar

from humanoid_robot.domain.wall import WallCommand, WallCommandResult
from humanoid_robot.events.base import BaseEvent


class WallCommandRequested(BaseEvent):
    """A video-wall command was requested (by voice intent or an operator)."""

    subject: ClassVar[str] = "wall.command.requested"
    schema_version: ClassVar[int] = 1

    command_id: str
    command: WallCommand
    source: str = "operator"  # voice / operator / test
    language: str = "ru"
    utterance: str = ""  # the recognised phrase that triggered it, if any


class WallCommandResulted(BaseEvent):
    """A video-wall command reached a terminal state."""

    subject: ClassVar[str] = "wall.command.result"
    schema_version: ClassVar[int] = 1

    command_id: str
    result: WallCommandResult
