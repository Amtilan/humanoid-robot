"""Reusable test doubles."""

from humanoid_robot.testing.event_bus import InMemoryEventBus
from humanoid_robot.testing.robot import MockRobotAdapter

__all__ = ["InMemoryEventBus", "MockRobotAdapter"]
