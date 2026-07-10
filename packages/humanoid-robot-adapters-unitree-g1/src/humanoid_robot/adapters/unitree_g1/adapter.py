"""Unitree G1 root adapter.

This module intentionally holds only the composition of the sub-ports. Each
concrete port implementation lives in its own module (arm.py, locomotion.py,
audio.py, battery.py) so hardware-specific quirks stay bounded.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Self

from pydantic import BaseModel, Field

from humanoid_robot.adapters.unitree_g1.arm import UnitreeG1Arm
from humanoid_robot.adapters.unitree_g1.audio_in import G1AudioInConfig, UnitreeG1AudioIn
from humanoid_robot.adapters.unitree_g1.audio_out import UnitreeG1AudioOut
from humanoid_robot.adapters.unitree_g1.battery import UnitreeG1Battery
from humanoid_robot.adapters.unitree_g1.imu import UnitreeG1Imu
from humanoid_robot.adapters.unitree_g1.locomotion import UnitreeG1LocomotionAdapter
from humanoid_robot.adapters.unitree_g1.manifest import build_manifest
from humanoid_robot.adapters.unitree_g1.sdk import require_sdk
from humanoid_robot.adapters.unitree_g1.temperature import UnitreeG1Temperature
from humanoid_robot.domain.robot import RobotCapabilities, RobotManifest

_LOG = logging.getLogger(__name__)


class UnitreeG1Settings(BaseModel):
    """Runtime settings for the G1 adapter."""

    network_interface: str = "eth0"
    mic_source: str = Field(default="g1", pattern="^(g1|alsa|r1)$")
    mic_alsa_device: str = "plughw:2,0"
    speaker_volume: int = Field(default=100, ge=0, le=100)
    hand_kind: str = Field(default="none", pattern="^(none|dex3|linker_o6|brainco|inspire)$")


@dataclass(slots=True)
class UnitreeG1Adapter:
    """Root adapter — wires up subs on `.start()`."""

    settings: UnitreeG1Settings = field(default_factory=UnitreeG1Settings)
    _manifest: RobotManifest | None = None
    _started: bool = False
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _locomotion: UnitreeG1LocomotionAdapter | None = None
    _arm: UnitreeG1Arm | None = None
    _battery: UnitreeG1Battery | None = None
    _imu: UnitreeG1Imu | None = None
    _temperature: UnitreeG1Temperature | None = None
    _audio_in: UnitreeG1AudioIn | None = None
    _audio_out: UnitreeG1AudioOut | None = None

    def __init__(self, **kwargs: object) -> None:
        # Adapter registry passes kwargs; validate through the settings model.
        self.settings = UnitreeG1Settings.model_validate(kwargs)
        self._manifest = None
        self._started = False
        self._start_lock = asyncio.Lock()
        self._locomotion = None
        self._arm = None
        self._battery = None
        self._imu = None
        self._audio_in = None
        self._audio_out = None
        self._temperature = None

    @classmethod
    def from_settings(cls, settings: UnitreeG1Settings) -> Self:
        obj = cls.__new__(cls)
        obj.settings = settings
        obj._manifest = None
        obj._started = False
        obj._start_lock = asyncio.Lock()
        obj._locomotion = None
        obj._arm = None
        obj._battery = None
        obj._imu = None
        obj._audio_in = None
        obj._audio_out = None
        obj._temperature = None
        return obj

    # ---- RobotAdapterPort ---------------------------------------------------

    @property
    def manifest(self) -> RobotManifest:
        if self._manifest is None:
            self._manifest = build_manifest(
                network_interface=self.settings.network_interface,
                mic_source=self.settings.mic_source,
                hand_kind=self.settings.hand_kind,
            )
        return self._manifest

    @property
    def capabilities(self) -> RobotCapabilities:
        return self.manifest.capabilities

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                return
            _LOG.info("unitree_g1.starting", extra={"interface": self.settings.network_interface})
            handles = require_sdk()  # raises UnitreeSdkNotAvailableError off-robot
            # DDS channel init is a process-global side effect; scoped to
            # this adapter's start() so tests never trigger it.
            handles.channel.ChannelFactoryInitialize(0, self.settings.network_interface)
            self._started = True
            _LOG.info("unitree_g1.started")

    async def stop(self) -> None:
        async with self._start_lock:
            if not self._started:
                return
            # The Unitree SDK does not expose a graceful shutdown for its
            # ChannelFactory; we release local resources and let process
            # teardown finalise DDS.
            self._started = False
            _LOG.info("unitree_g1.stopped")

    # ---- Sub-ports -----------------------------------------------------------
    #
    # The `locomotion` attribute is what the AdapterRunner picks up when
    # wiring the CommandDispatcher.  Splitting it out this way keeps the
    # LocomotionPort's `move`/`stop` methods from colliding with the root
    # adapter's lifecycle `stop()`.

    @property
    def locomotion(self) -> UnitreeG1LocomotionAdapter:
        if self._locomotion is None:
            self._locomotion = UnitreeG1LocomotionAdapter()
        return self._locomotion

    def attach_locomotion_client(self, client: object) -> None:
        """Test hook: inject a fake LocoClient before dispatching commands."""
        self._locomotion = UnitreeG1LocomotionAdapter(client=client)

    @property
    def arm(self) -> UnitreeG1Arm:
        if self._arm is None:
            self._arm = UnitreeG1Arm()
        return self._arm

    def attach_arm_client(
        self, client: object, *, action_map: dict[str, int] | None = None
    ) -> None:
        """Test hook: inject a fake G1ArmActionClient with an action_map."""
        arm = UnitreeG1Arm()
        arm.attach_client(client, action_map=action_map)
        self._arm = arm

    @property
    def battery(self) -> UnitreeG1Battery:
        if self._battery is None:
            self._battery = UnitreeG1Battery()
        return self._battery

    def attach_battery_source(self, source: object) -> None:
        """Test hook: inject a callable that reports battery percentage."""
        from collections.abc import Callable as _Callable

        if not isinstance(source, _Callable):  # type: ignore[arg-type]
            msg = "battery source must be a zero-arg callable"
            raise TypeError(msg)
        self._battery = UnitreeG1Battery(source=source)  # type: ignore[arg-type]

    @property
    def imu(self) -> UnitreeG1Imu:
        if self._imu is None:
            self._imu = UnitreeG1Imu()
        return self._imu

    def attach_imu_source(self, source: object) -> None:
        """Test hook: inject a callable that reports IMU samples."""
        from collections.abc import Callable as _Callable

        if not isinstance(source, _Callable):  # type: ignore[arg-type]
            msg = "imu source must be a zero-arg callable"
            raise TypeError(msg)
        self._imu = UnitreeG1Imu(source=source)  # type: ignore[arg-type]

    @property
    def temperature(self) -> UnitreeG1Temperature:
        if self._temperature is None:
            self._temperature = UnitreeG1Temperature()
        return self._temperature

    def attach_temperature_source(self, source: object) -> None:
        """Test hook: inject a callable that reports temperature zones."""
        from collections.abc import Callable as _Callable

        if not isinstance(source, _Callable):  # type: ignore[arg-type]
            msg = "temperature source must be a zero-arg callable"
            raise TypeError(msg)
        self._temperature = UnitreeG1Temperature(source=source)  # type: ignore[arg-type]

    @property
    def audio_in(self) -> UnitreeG1AudioIn:
        if self._audio_in is None:
            self._audio_in = UnitreeG1AudioIn(
                config=G1AudioInConfig(
                    interface_ip=self.settings.network_interface
                    if self.settings.mic_source == "g1"
                    else None
                ),
            )
        return self._audio_in

    def attach_audio_in(self, audio_in: UnitreeG1AudioIn) -> None:
        """Test hook: replace the multicast-mic port with a scripted one."""
        self._audio_in = audio_in

    @property
    def audio_out(self) -> UnitreeG1AudioOut:
        if self._audio_out is None:
            self._audio_out = UnitreeG1AudioOut(volume_pct=self.settings.speaker_volume)
        return self._audio_out

    def attach_audio_out_client(self, client: object) -> None:
        """Test hook: inject a fake AudioClient before playing."""
        audio_out = UnitreeG1AudioOut(volume_pct=self.settings.speaker_volume)
        audio_out.attach_client(client)
        self._audio_out = audio_out
