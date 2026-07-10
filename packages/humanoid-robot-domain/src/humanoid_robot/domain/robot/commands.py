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


class PostureKind(StrEnum):
    """Whole-body posture / locomotion FSM transitions.

    These map to the vendor LocoClient's mode calls. They are HIGH-RISK on
    a legged robot (a stand/balance transition makes the robot bear its own
    weight and can fall), which is exactly why they run through the safety
    gate — estop-guarded, rate-limited, and audited — instead of a direct
    SDK call. `damp` / `zero_torque` are the safe holding states; the
    stand/balance transitions require the robot free-standing on the floor.
    """

    DAMP = "damp"
    ZERO_TORQUE = "zero_torque"
    SIT = "sit"
    SQUAT = "squat"
    STAND_UP = "stand_up"
    BALANCE_STAND = "balance_stand"
    HIGH_STAND = "high_stand"
    LOW_STAND = "low_stand"
    STOP_MOVE = "stop_move"


class PostureCommand(BaseModel):
    """Request a whole-body posture / locomotion FSM transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    posture: PostureKind


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
