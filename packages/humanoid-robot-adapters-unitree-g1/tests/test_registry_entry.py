"""Verify the entry-point registration is discoverable at runtime."""

from __future__ import annotations

from humanoid_robot.adapters.unitree_g1 import UnitreeG1Adapter
from humanoid_robot.plugins_sdk import AdapterRegistry


class TestG1EntryPoint:
    def test_registry_finds_g1(self) -> None:
        registry = AdapterRegistry.discover()
        assert "unitree_g1_edu" in registry.names()

    def test_registry_builds_g1(self) -> None:
        registry = AdapterRegistry.discover()
        adapter = registry.build("unitree_g1_edu", network_interface="eth10")
        assert isinstance(adapter, UnitreeG1Adapter)
        assert adapter.settings.network_interface == "eth10"
