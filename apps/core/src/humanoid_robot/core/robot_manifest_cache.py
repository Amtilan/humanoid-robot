"""Robot manifest cache — subscribes to `robot.adapter.ready` events.

The FastAPI process does not run the robot adapter itself (that is
`cortex-robot-adapter`'s job).  We simply mirror the latest manifest we
have seen on the event bus, keyed by adapter name, so the operator UI can
render "what robot is connected right now" without having to query the
adapter directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from humanoid_robot.domain.robot import RobotManifest
from humanoid_robot.domain.shared import Timestamp
from humanoid_robot.events import BaseEvent, RobotAdapterReady
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-core.robot_manifest_cache")


class RobotManifestSnapshot(BaseModel):
    """Cached manifest + freshness metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_name: str
    adapter_version: str
    manifest: RobotManifest
    observed_at: Timestamp


@dataclass(slots=True)
class RobotManifestCache:
    """In-memory map: adapter_name → last-seen manifest."""

    _cache: dict[str, RobotManifestSnapshot] = field(default_factory=dict)

    async def start(self, bus: EventBusPort) -> Subscription:
        return await bus.subscribe(RobotAdapterReady.subject, self._on_ready)

    def all(self) -> list[RobotManifestSnapshot]:
        return sorted(self._cache.values(), key=lambda s: s.adapter_name)

    def get(self, adapter_name: str) -> RobotManifestSnapshot | None:
        return self._cache.get(adapter_name)

    async def _on_ready(self, event: BaseEvent) -> None:
        if not isinstance(event, RobotAdapterReady):
            return
        manifest = RobotManifest(
            adapter_name=event.adapter_name,
            adapter_version=event.adapter_version,
            robot_model=event.robot_model,
            capabilities=event.capabilities,
        )
        snapshot = RobotManifestSnapshot(
            adapter_name=event.adapter_name,
            adapter_version=event.adapter_version,
            manifest=manifest,
            observed_at=datetime.now().astimezone(),
        )
        self._cache[event.adapter_name] = snapshot
        _LOG.info(
            "robot_manifest_cache.updated",
            adapter=event.adapter_name,
            version=event.adapter_version,
        )
