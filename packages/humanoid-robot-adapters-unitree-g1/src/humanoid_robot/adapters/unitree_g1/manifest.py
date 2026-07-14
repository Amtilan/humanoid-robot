"""Build a `RobotManifest` for a Unitree G1 Edu."""

from __future__ import annotations

from humanoid_robot.domain.robot import (
    ArmCapability,
    AudioCapability,
    BatteryCapability,
    CameraCapability,
    HandCapability,
    HeadCapability,
    LocomotionCapability,
    LocomotionKind,
    RobotCapabilities,
    RobotManifest,
    RobotModel,
)

_ADAPTER_NAME = "unitree_g1_edu"
_ADAPTER_VERSION = "0.0.0"

# Canonical gesture names exposed by the vendor `G1ArmActionClient.action_map`
# and used by `g1_intelligence`.
G1_GESTURES: tuple[str, ...] = (
    "high wave",
    "face wave",
    "high five",
    "right kiss",
    "right hand up",
    "x-ray",
    "release arm",
)


def build_manifest(
    *,
    network_interface: str,
    mic_source: str = "g1",
    mic_channels: int = 6,
    speaker_kind: str = "unitree_audio_client",
    hand_kind: str = "none",
) -> RobotManifest:
    """Build a manifest that reflects the physical robot's current config."""
    return RobotManifest(
        adapter_name=_ADAPTER_NAME,
        adapter_version=_ADAPTER_VERSION,
        robot_model=RobotModel(vendor="unitree", family="g1", variant="edu"),
        capabilities=RobotCapabilities(
            locomotion=LocomotionCapability(
                kind=LocomotionKind.LEGGED_BIPEDAL,
                max_speed_mps=1.5,
                supports_stop=True,
            ),
            arms=(
                ArmCapability(arm_id="left", dof=7, gestures=G1_GESTURES),
                ArmCapability(arm_id="right", dof=7, gestures=G1_GESTURES),
            ),
            hands=(
                HandCapability(hand_id="left", kind=hand_kind, dof=0 if hand_kind == "none" else 6),
                HandCapability(
                    hand_id="right", kind=hand_kind, dof=0 if hand_kind == "none" else 6
                ),
            ),
            head=HeadCapability(dof=3),
            audio_in=AudioCapability(
                kind={"g1": "g1_multicast", "r1": "r1_multicast"}.get(mic_source, "alsa"),
                channels=mic_channels,
                sample_rate_hz=16_000,
            ),
            audio_out=AudioCapability(kind=speaker_kind, channels=1, sample_rate_hz=16_000),
            battery=BatteryCapability(reports_percentage=True),
            # Front camera comes from the vendor VideoClient over DDS (there is
            # no local sensor on this Jetson); frames are served as MJPEG by
            # camera_mjpeg.py. Resolution/fps observed live: 1280x720 JPEG.
            cameras=(CameraCapability(camera_id="front", resolution_wh=(1280, 720), fps=12),),
        ),
        transport_hint="cyclonedds",
        network_interface=network_interface,
    )
