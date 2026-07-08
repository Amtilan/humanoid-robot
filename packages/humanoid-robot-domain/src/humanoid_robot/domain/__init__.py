"""Domain layer — pure entities, value objects, and domain services.

The domain is split into bounded contexts. Each subpackage is a self-contained
model of one area of the robot's behaviour.
"""

from humanoid_robot.domain import knowledge, robot, telemetry, voice

__all__ = ["knowledge", "robot", "telemetry", "voice"]
