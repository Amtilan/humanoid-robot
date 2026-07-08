"""Discovery of installed plugins via `humanoid_robot.plugins` entry points."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Self, cast

from humanoid_robot.plugins_sdk.plugin import PluginPort

PLUGIN_ENTRY_POINT_GROUP = "humanoid_robot.plugins"


class UnknownPluginError(LookupError):
    """Raised when the caller asks for a plugin that has not registered."""


@dataclass(slots=True, frozen=True)
class PluginEntry:
    """One discovered plugin registration."""

    name: str
    factory: Callable[..., PluginPort]
    distribution: str | None
    version: str | None

    def build(self, **kwargs: Any) -> PluginPort:  # noqa: ANN401
        return self.factory(**kwargs)


@dataclass(slots=True)
class PluginRegistry:
    """Read-only view of discovered plugins."""

    _entries: dict[str, PluginEntry] = field(default_factory=dict)

    @classmethod
    def discover(cls, *, group: str = PLUGIN_ENTRY_POINT_GROUP) -> Self:
        entries: dict[str, PluginEntry] = {}
        for ep in _iter_entry_points(group):
            entries[ep.name] = _load_entry(ep)
        return cls(_entries=entries)

    @classmethod
    def from_entries(cls, entries: Iterable[PluginEntry]) -> Self:
        return cls(_entries={e.name: e for e in entries})

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, name: str) -> PluginEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._entries)) or "<none>"
            msg = f"no plugin named {name!r} is registered; available: {available}"
            raise UnknownPluginError(msg) from exc

    def build(self, name: str, **kwargs: Any) -> PluginPort:  # noqa: ANN401
        return self.get(name).build(**kwargs)


def _iter_entry_points(group: str) -> Iterable[EntryPoint]:
    return cast("Iterable[EntryPoint]", entry_points(group=group))


def _load_entry(ep: EntryPoint) -> PluginEntry:
    factory: Callable[..., PluginPort] = ep.load()
    dist = ep.dist
    return PluginEntry(
        name=ep.name,
        factory=factory,
        distribution=dist.name if dist is not None else None,
        version=dist.version if dist is not None else None,
    )
