"""RobotManifestCache tests using InMemoryEventBus."""

from __future__ import annotations

from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.domain.robot import (
    LocomotionCapability,
    LocomotionKind,
    RobotCapabilities,
    RobotModel,
)
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotAdapterReady
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.testing import InMemoryEventBus


def _mk_ready_event(adapter_name: str = "unitree_g1_edu") -> RobotAdapterReady:
    return RobotAdapterReady(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        adapter_name=adapter_name,
        adapter_version="0.0.1",
        robot_model=RobotModel(vendor="unitree", family="g1", variant="edu"),
        capabilities=RobotCapabilities(
            locomotion=LocomotionCapability(kind=LocomotionKind.LEGGED_BIPEDAL, max_speed_mps=1.5),
        ),
    )


class TestRobotManifestCache:
    async def test_empty_cache_initially(self) -> None:
        cache = RobotManifestCache()
        assert cache.all() == []
        assert cache.get("anything") is None

    async def test_ready_event_populates_cache(self) -> None:
        bus = InMemoryEventBus()
        cache = RobotManifestCache()
        await cache.start(bus)
        await bus.publish(_mk_ready_event())
        snapshots = cache.all()
        assert len(snapshots) == 1
        assert snapshots[0].adapter_name == "unitree_g1_edu"
        assert snapshots[0].manifest.robot_model.slug == "unitree_g1_edu"

    async def test_later_event_overwrites_earlier_for_same_adapter(self) -> None:
        bus = InMemoryEventBus()
        cache = RobotManifestCache()
        await cache.start(bus)
        await bus.publish(_mk_ready_event())
        first = cache.get("unitree_g1_edu")
        assert first is not None
        await bus.publish(_mk_ready_event())
        second = cache.get("unitree_g1_edu")
        assert second is not None
        assert second.observed_at >= first.observed_at

    async def test_multiple_adapters_tracked_independently(self) -> None:
        bus = InMemoryEventBus()
        cache = RobotManifestCache()
        await cache.start(bus)
        await bus.publish(_mk_ready_event("unitree_g1_edu"))
        await bus.publish(_mk_ready_event("mock_robot"))
        names = {s.adapter_name for s in cache.all()}
        assert names == {"unitree_g1_edu", "mock_robot"}
