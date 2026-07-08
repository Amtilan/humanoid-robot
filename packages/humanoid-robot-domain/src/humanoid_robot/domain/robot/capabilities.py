"""Robot capability model.

`RobotManifest` is the single source of truth about *what a robot can do*.
Each concrete `RobotAdapter` produces exactly one manifest at boot; the rest of
the platform reads it and adapts UI/plugins/logic accordingly.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LocomotionKind(StrEnum):
    """Coarse locomotion taxonomy — enough to drive UI/plugins."""

    LEGGED_BIPEDAL = "legged_bipedal"
    LEGGED_QUADRUPED = "legged_quadruped"
    WHEELED = "wheeled"
    TRACKED = "tracked"
    STATIC = "static"


class LocomotionCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LocomotionKind
    max_speed_mps: float = Field(ge=0.0)
    supports_stop: bool = True


class ArmCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    dof: int = Field(ge=1, le=32)
    gestures: tuple[str, ...] = ()


class HandCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hand_id: str
    kind: str  # e.g. "dex3", "linker_o6", "brainco", "inspire", "none"
    dof: int = Field(ge=0, le=32)


class HeadCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dof: int = Field(ge=0, le=6)


class AudioCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str  # transport tag, e.g. "g1_multicast", "alsa", "r1_multicast"
    channels: int = Field(ge=1, le=16)
    sample_rate_hz: int = Field(gt=0, le=192_000)


class BatteryCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reports_percentage: bool = True
    reports_voltage: bool = False


class CameraCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    camera_id: str
    resolution_wh: tuple[int, int] = Field(min_length=2, max_length=2)
    fps: int = Field(gt=0, le=240)


class RobotCapabilities(BaseModel):
    """Aggregate of everything a robot can do."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locomotion: LocomotionCapability | None = None
    arms: tuple[ArmCapability, ...] = ()
    hands: tuple[HandCapability, ...] = ()
    head: HeadCapability | None = None
    audio_in: AudioCapability | None = None
    audio_out: AudioCapability | None = None
    battery: BatteryCapability | None = None
    cameras: tuple[CameraCapability, ...] = ()


class RobotModel(BaseModel):
    """Vendor + model identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vendor: str
    family: str
    variant: str

    @property
    def slug(self) -> str:
        return f"{self.vendor}_{self.family}_{self.variant}".lower()


class RobotManifest(BaseModel):
    """Everything the core needs to know about the connected robot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_name: str
    adapter_version: str
    robot_model: RobotModel
    capabilities: RobotCapabilities
    transport_hint: str | None = None  # e.g. "cyclonedds", "ros2", "serial"
    network_interface: str | None = None  # e.g. "eth10"
