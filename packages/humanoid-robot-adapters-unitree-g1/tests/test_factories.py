"""Entry-point factory tests for the G1 audio ports."""

from __future__ import annotations

import pytest

from humanoid_robot.adapters.unitree_g1 import UnitreeSdkNotAvailableError
from humanoid_robot.adapters.unitree_g1.audio_in import G1AudioInConfig
from humanoid_robot.adapters.unitree_g1.factories import (
    unitree_g1_audio_in,
    unitree_g1_audio_out,
)
from humanoid_robot.plugins_sdk import AdapterRegistry


class TestFactories:
    def test_audio_in_factory_builds_configured_port(self) -> None:
        port = unitree_g1_audio_in(input_channels=6, downmix_channel=1)
        assert port.config == G1AudioInConfig(input_channels=6, downmix_channel=1)

    def test_audio_out_factory_raises_without_sdk(self) -> None:
        # The audio-out factory triggers a real DDS init; on any machine
        # without the vendor SDK we get UnitreeSdkNotAvailableError, which
        # is exactly the fallback contract we want.
        with pytest.raises(UnitreeSdkNotAvailableError):
            unitree_g1_audio_out(network_interface="eth10")

    def test_audio_in_group_registered(self) -> None:
        from importlib.metadata import entry_points

        names = sorted(ep.name for ep in entry_points(group="humanoid_robot.audio_in_adapters"))
        assert "unitree_g1" in names

    def test_audio_out_group_registered(self) -> None:
        from importlib.metadata import entry_points

        names = sorted(ep.name for ep in entry_points(group="humanoid_robot.audio_out_adapters"))
        assert "unitree_g1" in names

    def test_registry_helper_lists_audio_ports(self) -> None:
        # `AdapterRegistry.discover` is scoped to robot_adapters by default;
        # the audio groups need explicit discovery, but the underlying
        # importlib.metadata plumbing must agree.
        registry = AdapterRegistry.discover(group="humanoid_robot.audio_in_adapters")
        assert "unitree_g1" in registry.names()
