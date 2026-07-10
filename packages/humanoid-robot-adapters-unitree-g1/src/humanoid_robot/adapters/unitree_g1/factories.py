"""Entry-point factories for G1 audio ports.

Both factories stay lazy: neither of them touches the vendor SDK at
construction time.  The socket-backed multicast mic (`UnitreeG1AudioIn`)
opens its socket on the first `.stream()` iteration; the DDS-backed
speaker (`UnitreeG1AudioOut`) loads the SDK and calls
`ChannelFactoryInitialize` on the first `.play()`.  This means voice
composition can pull them from `entry_points` on a developer laptop
without ``unitree_sdk2py`` installed — playback would raise the
SDK-unavailable error, but the audio ports themselves construct fine.
"""

from __future__ import annotations

from humanoid_robot.adapters.unitree_g1.audio_in import (
    G1AudioInConfig,
    UnitreeG1AudioIn,
)
from humanoid_robot.adapters.unitree_g1.audio_out import UnitreeG1AudioOut


def unitree_g1_audio_in(**kwargs: object) -> UnitreeG1AudioIn:
    """``humanoid_robot.audio_in_adapters`` entry-point.

    Any kwargs are forwarded to ``G1AudioInConfig`` — no vendor SDK is
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
    """``humanoid_robot.audio_out_adapters`` entry-point.

    The vendor SDK is loaded lazily on the first ``.play()``; the DDS
    channel factory is initialised on the same call, exactly once per
    process, using ``network_interface`` as the bind hint.
    """
    return UnitreeG1AudioOut(
        volume_pct=volume_pct,
        app_name=app_name,
        network_interface=network_interface,
    )
