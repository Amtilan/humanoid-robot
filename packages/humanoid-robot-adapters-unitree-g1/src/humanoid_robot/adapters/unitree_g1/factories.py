"""Entry-point factories for G1 audio ports.

`UnitreeG1AudioOut` needs `SdkHandles` at construction. That is fine for
the robot-adapter runner (which builds them once and shares them), but not
convenient for the voice runner which resolves ports from `entry_points`
with only a plain-kwargs config. These factories accept the CLI-friendly
config and load the vendor SDK lazily.
"""

from __future__ import annotations

from humanoid_robot.adapters.unitree_g1.audio_in import (
    G1AudioInConfig,
    UnitreeG1AudioIn,
)
from humanoid_robot.adapters.unitree_g1.audio_out import UnitreeG1AudioOut
from humanoid_robot.adapters.unitree_g1.sdk import require_sdk


def unitree_g1_audio_in(**kwargs: object) -> UnitreeG1AudioIn:
    """`humanoid_robot.audio_in_adapters` entry-point.

    Any kwargs are forwarded to `G1AudioInConfig` — no vendor SDK is
    required (the port sits on a plain multicast socket).
    """
    config = G1AudioInConfig.model_validate(kwargs)
    return UnitreeG1AudioIn(config=config)


def unitree_g1_audio_out(
    *,
    network_interface: str = "eth0",
    volume_pct: int = 100,
    app_name: str = "cortex",
    **_extras: object,
) -> UnitreeG1AudioOut:
    """`humanoid_robot.audio_out_adapters` entry-point.

    Initialises the DDS channel and loads the vendor SDK on first call so
    the voice-runner composition can pull an `AudioOutPort` from the
    registry without direct knowledge of `unitree_sdk2py`.
    """
    handles = require_sdk()
    handles.channel.ChannelFactoryInitialize(0, network_interface)
    return UnitreeG1AudioOut(_sdk=handles, volume_pct=volume_pct, app_name=app_name)
