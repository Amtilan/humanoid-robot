"""Runtime plugin manager.

Owns the active/inactive state of every plugin known to the platform:

    - Discovery goes through `PluginRegistry` (entry points).
    - Activation instantiates a plugin, hands it a `PluginContext(bus)`, and
      awaits `plugin.activate()`.
    - Deactivation awaits `plugin.deactivate()` and drops the instance.

Concurrent operations on the same plugin name are serialised through a
per-name lock so an operator cannot double-activate a plugin by clicking
fast enough.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from humanoid_robot.observability import get_logger
from humanoid_robot.plugins_sdk import (
    PluginContext,
    PluginManifest,
    PluginPort,
    PluginRegistry,
)
from humanoid_robot.ports import EventBusPort

_LOG = get_logger("cortex-core.plugin_manager")


class PluginStatus(BaseModel):
    """Snapshot of a plugin's registration + active state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    distribution: str | None
    version: str | None
    is_active: bool
    manifest: PluginManifest | None


class PluginNotFoundError(LookupError):
    """The plugin is not registered in the runtime."""


class PluginAlreadyActiveError(RuntimeError):
    """Cannot activate an already-active plugin."""


class PluginNotActiveError(RuntimeError):
    """Cannot deactivate a plugin that is not active."""


@dataclass(slots=True)
class PluginManager:
    """Lifecycle owner for platform plugins."""

    registry: PluginRegistry
    bus: EventBusPort
    _active: dict[str, PluginPort] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _lock_for(self, name: str) -> asyncio.Lock:
        lock = self._locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[name] = lock
        return lock

    def list_statuses(self) -> list[PluginStatus]:
        statuses: list[PluginStatus] = []
        for name in self.registry.names():
            entry = self.registry.get(name)
            active_instance = self._active.get(name)
            manifest = active_instance.manifest if active_instance is not None else None
            statuses.append(
                PluginStatus(
                    name=name,
                    distribution=entry.distribution,
                    version=entry.version,
                    is_active=active_instance is not None,
                    manifest=manifest,
                )
            )
        return statuses

    async def activate(self, name: str) -> PluginStatus:
        if name not in self.registry.names():
            msg = f"plugin {name!r} is not registered"
            raise PluginNotFoundError(msg)
        async with self._lock_for(name):
            if name in self._active:
                msg = f"plugin {name!r} is already active"
                raise PluginAlreadyActiveError(msg)
            entry = self.registry.get(name)
            plugin = entry.build()
            await plugin.activate(PluginContext(bus=self.bus))
            self._active[name] = plugin
            _LOG.info("plugin_manager.activated", plugin=name)
        return self._status_for(name)

    async def deactivate(self, name: str) -> PluginStatus:
        if name not in self.registry.names():
            msg = f"plugin {name!r} is not registered"
            raise PluginNotFoundError(msg)
        async with self._lock_for(name):
            plugin = self._active.pop(name, None)
            if plugin is None:
                msg = f"plugin {name!r} is not active"
                raise PluginNotActiveError(msg)
            await plugin.deactivate()
            _LOG.info("plugin_manager.deactivated", plugin=name)
        return self._status_for(name)

    async def deactivate_all(self) -> None:
        """Called by the container on shutdown."""
        for name in list(self._active):
            try:
                await self.deactivate(name)
            except Exception:
                _LOG.exception("plugin_manager.deactivate_failed", plugin=name)

    def _status_for(self, name: str) -> PluginStatus:
        entry = self.registry.get(name)
        active_instance = self._active.get(name)
        return PluginStatus(
            name=name,
            distribution=entry.distribution,
            version=entry.version,
            is_active=active_instance is not None,
            manifest=active_instance.manifest if active_instance is not None else None,
        )
