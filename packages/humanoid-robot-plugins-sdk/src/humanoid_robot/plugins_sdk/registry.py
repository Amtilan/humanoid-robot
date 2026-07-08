"""Robot adapter registry backed by ``importlib.metadata`` entry points."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Self, cast

from humanoid_robot.ports import RobotAdapterPort

ADAPTER_ENTRY_POINT_GROUP = "humanoid_robot.robot_adapters"


class UnknownAdapterError(LookupError):
    """Raised when the caller asks for an adapter that has not registered."""


@dataclass(slots=True, frozen=True)
class AdapterEntry:
    """One discovered registration."""

    name: str
    factory: Callable[..., RobotAdapterPort]
    distribution: str | None
    version: str | None

    def build(self, **kwargs: Any) -> RobotAdapterPort:
        """Instantiate the adapter with the given runtime kwargs."""
        return self.factory(**kwargs)


@dataclass(slots=True)
class AdapterRegistry:
    """Read-only view of discovered adapters."""

    _entries: dict[str, AdapterEntry] = field(default_factory=dict)

    @classmethod
    def discover(cls, *, group: str = ADAPTER_ENTRY_POINT_GROUP) -> Self:
        """Load every registered entry point in the current interpreter."""
        entries: dict[str, AdapterEntry] = {}
        for ep in _iter_entry_points(group):
            entries[ep.name] = _load_entry(ep)
        return cls(_entries=entries)

    @classmethod
    def from_entries(cls, entries: Iterable[AdapterEntry]) -> Self:
        """Build a registry directly from `AdapterEntry` objects (tests, DI)."""
        return cls(_entries={e.name: e for e in entries})

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, name: str) -> AdapterEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._entries)) or "<none>"
            msg = f"no adapter named {name!r} is registered; available: {available}"
            raise UnknownAdapterError(msg) from exc

    def build(self, name: str, **kwargs: Any) -> RobotAdapterPort:
        return self.get(name).build(**kwargs)


def _iter_entry_points(group: str) -> Iterable[EntryPoint]:
    # `select` is available on modern importlib.metadata (Python 3.10+).
    return cast("Iterable[EntryPoint]", entry_points(group=group))


def _load_entry(ep: EntryPoint) -> AdapterEntry:
    factory: Callable[..., RobotAdapterPort] = ep.load()
    dist = ep.dist
    return AdapterEntry(
        name=ep.name,
        factory=factory,
        distribution=dist.name if dist is not None else None,
        version=dist.version if dist is not None else None,
    )
