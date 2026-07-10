"""Domain-level commands sent to robot ports."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MoveCommand(BaseModel):
    """A body-frame velocity command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    linear_x_mps: float = Field(ge=-5.0, le=5.0)
    linear_y_mps: float = Field(ge=-5.0, le=5.0)
    angular_z_rps: float = Field(ge=-6.28, le=6.28)
    duration_ms: int = Field(ge=0, le=60_000, default=0)


class StopCommand(BaseModel):
    """Immediate stop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = "user_requested"


class HeadPoseCommand(BaseModel):
    """Absolute head orientation (radians)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pitch_rad: float = Field(ge=-1.0, le=1.0)  # ~±57°
    yaw_rad: float = Field(ge=-1.5, le=1.5)  # ~±86°
    duration_ms: int = Field(ge=0, le=10_000, default=0)


class MoveOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_BY_POLICY = "rejected_by_policy"
    HARDWARE_ERROR = "hardware_error"
    TIMEOUT = "timeout"


class RobotCommandResult(BaseModel):
    """Uniform result for any command sent through a robot port."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: MoveOutcome
    error_code: str | None = None
    error_message: str | None = None
