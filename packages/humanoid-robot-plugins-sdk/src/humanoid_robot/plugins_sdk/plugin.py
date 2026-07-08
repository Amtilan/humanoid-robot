"""Plugin lifecycle contract.

A plugin is a self-contained unit that hooks into platform events. It has a
manifest describing metadata + declared permissions and a lifecycle:

    load → activate → (event handlers fire until) → deactivate → unload

Plugins subscribe/publish through the same `EventBusPort` as everything else,
so they can be tested with `InMemoryEventBus`. No plugin should reach into
sibling modules directly — Event Bus + provided ports are the only allowed
integration surface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.ports import EventBusPort


class PluginManifest(BaseModel):
    """Metadata + declared permissions for a plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    # Permissions the plugin declares it needs. The runtime does not yet
    # enforce these — the plugin registry surfaces them so operators can
    # review before enabling a plugin.
    permissions: tuple[str, ...] = Field(default_factory=tuple)
    # NATS subject patterns the plugin intends to subscribe to. Purely
    # advisory; the plugin still subscribes explicitly through
    # `PluginContext.bus.subscribe(...)`.
    subscribes: tuple[str, ...] = Field(default_factory=tuple)


class PluginContext(BaseModel):
    """Resources handed to a plugin at activation."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    bus: EventBusPort


@runtime_checkable
class PluginPort(Protocol):
    """The single contract every plugin implements."""

    @property
    def manifest(self) -> PluginManifest: ...

    async def activate(self, context: PluginContext) -> None: ...

    async def deactivate(self) -> None: ...
