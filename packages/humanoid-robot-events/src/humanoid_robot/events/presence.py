"""Visitor presence events (camera-based detection)."""

from __future__ import annotations

from typing import ClassVar

from humanoid_robot.events.base import BaseEvent


class VisitorDetected(BaseEvent):
    """A visitor appeared in front of the robot's camera.

    Published once per visit (the detector re-arms only after the scene has
    been quiet again), so consumers may greet without extra debouncing —
    though the greeter keeps its own cooldown as a second line of defence.
    """

    subject: ClassVar[str] = "visitor.detected"
    schema_version: ClassVar[int] = 1

    score: float  # detector confidence / motion fraction, 0..1
    source: str = "camera"
