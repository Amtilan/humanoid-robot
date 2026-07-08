"""PluginManager tests using in-process registry + InMemoryEventBus."""

from __future__ import annotations

import pytest

from humanoid_robot.core.plugin_manager import (
    PluginAlreadyActiveError,
    PluginManager,
    PluginNotActiveError,
    PluginNotFoundError,
)
from humanoid_robot.plugins_sdk import (
    PluginContext,
    PluginEntry,
    PluginManifest,
    PluginRegistry,
)
from humanoid_robot.testing import InMemoryEventBus


class _StubPlugin:
    def __init__(self, name: str = "stub") -> None:
        self._manifest = PluginManifest(name=name, version="0.1.0")
        self.activate_calls = 0
        self.deactivate_calls = 0

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    async def activate(self, context: PluginContext) -> None:
        assert context.bus is not None
        self.activate_calls += 1

    async def deactivate(self) -> None:
        self.deactivate_calls += 1


def _stub_factory(**_kwargs: object) -> _StubPlugin:
    return _StubPlugin()


def _mk_manager() -> tuple[PluginManager, PluginRegistry]:
    registry = PluginRegistry.from_entries(
        [
            PluginEntry(
                name="alpha",
                factory=_stub_factory,
                distribution="pkg-alpha",
                version="0.1.0",
            ),
            PluginEntry(
                name="beta",
                factory=_stub_factory,
                distribution="pkg-beta",
                version="0.2.0",
            ),
        ]
    )
    bus = InMemoryEventBus()
    return PluginManager(registry=registry, bus=bus), registry


class TestPluginManager:
    async def test_list_statuses_returns_registered_names(self) -> None:
        manager, _ = _mk_manager()
        statuses = manager.list_statuses()
        assert [s.name for s in statuses] == ["alpha", "beta"]
        assert all(not s.is_active for s in statuses)

    async def test_activate_marks_plugin_active(self) -> None:
        manager, _ = _mk_manager()
        status = await manager.activate("alpha")
        assert status.is_active
        assert status.manifest is not None
        assert status.manifest.name == "stub"

    async def test_double_activate_raises(self) -> None:
        manager, _ = _mk_manager()
        await manager.activate("alpha")
        with pytest.raises(PluginAlreadyActiveError):
            await manager.activate("alpha")

    async def test_deactivate_marks_plugin_inactive(self) -> None:
        manager, _ = _mk_manager()
        await manager.activate("alpha")
        status = await manager.deactivate("alpha")
        assert not status.is_active
        assert status.manifest is None

    async def test_deactivate_before_activate_raises(self) -> None:
        manager, _ = _mk_manager()
        with pytest.raises(PluginNotActiveError):
            await manager.deactivate("alpha")

    async def test_unknown_plugin_raises_not_found(self) -> None:
        manager, _ = _mk_manager()
        with pytest.raises(PluginNotFoundError):
            await manager.activate("nonexistent")
        with pytest.raises(PluginNotFoundError):
            await manager.deactivate("nonexistent")

    async def test_deactivate_all_stops_every_active_plugin(self) -> None:
        manager, _ = _mk_manager()
        await manager.activate("alpha")
        await manager.activate("beta")
        await manager.deactivate_all()
        assert all(not s.is_active for s in manager.list_statuses())
