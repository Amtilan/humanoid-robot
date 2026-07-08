"""PluginRegistry tests using in-process factories."""

from __future__ import annotations

import pytest

from humanoid_robot.plugins_sdk import (
    PluginContext,
    PluginEntry,
    PluginManifest,
    PluginRegistry,
    UnknownPluginError,
)
from humanoid_robot.testing import InMemoryEventBus


class _StubPlugin:
    def __init__(self, name: str = "stub") -> None:
        self._manifest = PluginManifest(name=name, version="0.1.0", description="stub")
        self.activated = False
        self.deactivated = False

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    async def activate(self, context: PluginContext) -> None:
        assert context.bus is not None
        self.activated = True

    async def deactivate(self) -> None:
        self.deactivated = True


def _stub_factory(**_kwargs: object) -> _StubPlugin:
    return _StubPlugin()


class TestPluginRegistry:
    def test_from_entries_sorts_names(self) -> None:
        reg = PluginRegistry.from_entries(
            [
                PluginEntry(name="beta", factory=_stub_factory, distribution=None, version=None),
                PluginEntry(name="alpha", factory=_stub_factory, distribution=None, version=None),
            ]
        )
        assert reg.names() == ("alpha", "beta")

    def test_missing_plugin_lists_available(self) -> None:
        reg = PluginRegistry.from_entries(
            [PluginEntry(name="alpha", factory=_stub_factory, distribution=None, version=None)]
        )
        with pytest.raises(UnknownPluginError, match="available: alpha"):
            reg.build("missing")

    def test_build_returns_plugin_instance(self) -> None:
        reg = PluginRegistry.from_entries(
            [PluginEntry(name="alpha", factory=_stub_factory, distribution=None, version=None)]
        )
        plugin = reg.build("alpha")
        assert isinstance(plugin, _StubPlugin)

    async def test_activate_deactivate_lifecycle(self) -> None:
        bus = InMemoryEventBus()
        plugin = _StubPlugin()
        await plugin.activate(PluginContext(bus=bus))
        assert plugin.activated
        await plugin.deactivate()
        assert plugin.deactivated

    def test_discover_returns_empty_when_group_missing(self) -> None:
        reg = PluginRegistry.discover(group="humanoid_robot.tests.__nonexistent__")
        assert reg.names() == ()
