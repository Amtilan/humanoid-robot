"""AdapterRunner tests — use a fake registry + fake bus, no NATS required."""

from __future__ import annotations

import asyncio

import pytest

from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotAdapterReady
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.plugins_sdk import AdapterEntry, AdapterRegistry
from humanoid_robot.robot_adapter_app.runner import AdapterRunner
from humanoid_robot.robot_adapter_app.settings import RobotAdapterSettings
from humanoid_robot.testing import InMemoryEventBus, MockRobotAdapter


def _mock_factory(**_: object) -> MockRobotAdapter:
    return MockRobotAdapter()


def _mk_settings() -> RobotAdapterSettings:
    return RobotAdapterSettings(adapter_name="mock")


def _mk_registry() -> AdapterRegistry:
    return AdapterRegistry.from_entries(
        [AdapterEntry(name="mock", factory=_mock_factory, distribution=None, version=None)]
    )


class TestAdapterRunner:
    async def test_publishes_ready_and_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bus = InMemoryEventBus()
        runner = AdapterRunner(settings=_mk_settings(), registry=_mk_registry())

        # Redirect the NATS bus factory to our in-memory fake — avoids real NATS.
        async def fake_start(self_: AdapterRunner) -> None:
            self_._bus = bus
            adapter = self_.registry.build(self_.settings.adapter_name)
            await adapter.start()
            self_._adapter = adapter
            await bus.publish(
                RobotAdapterReady(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer="tests",
                    ),
                    adapter_name=adapter.manifest.adapter_name,
                    adapter_version=adapter.manifest.adapter_version,
                    robot_model=adapter.manifest.robot_model,
                    capabilities=adapter.capabilities,
                )
            )

        monkeypatch.setattr(AdapterRunner, "_start", fake_start)

        # request_stop before .run() so it exits immediately after start.
        async def _drive() -> None:
            task = asyncio.create_task(runner.run())
            await asyncio.sleep(0)  # let start run
            runner.request_stop()
            await task

        await _drive()

        subjects = [type(ev).subject for ev in bus.published]
        assert "robot.adapter.ready" in subjects
        assert "system.shutting_down" in subjects


class TestSettings:
    def test_defaults(self) -> None:
        s = _mk_settings()
        assert s.adapter_name == "mock"
        assert s.nats.servers[0].startswith("nats://")

    def test_model_copy_updates_nats(self) -> None:
        s = _mk_settings()
        new = s.model_copy(
            update={"nats": s.nats.model_copy(update={"servers": ("nats://x:4222",)})}
        )
        assert new.nats.servers == ("nats://x:4222",)
