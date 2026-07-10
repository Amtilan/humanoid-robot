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
from humanoid_robot.adapters.unitree_g1.battery import UnitreeG1Battery
from humanoid_robot.adapters.unitree_g1.locomotion import UnitreeG1LocomotionAdapter
from humanoid_robot.adapters.unitree_g1.manifest import build_manifest
from humanoid_robot.adapters.unitree_g1.sdk import require_sdk
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

    def __init__(self, **kwargs: object) -> None:
        # Adapter registry passes kwargs; validate through the settings model.
        self.settings = UnitreeG1Settings.model_validate(kwargs)
        self._manifest = None
        self._started = False
        self._start_lock = asyncio.Lock()
        self._locomotion = None
        self._arm = None
        self._battery = None

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
