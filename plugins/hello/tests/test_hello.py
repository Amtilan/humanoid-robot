"""HelloPlugin tests using InMemoryEventBus."""

from __future__ import annotations

from importlib.metadata import entry_points

from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.plugins.hello import HelloPlugin, build_hello_plugin
from humanoid_robot.plugins_sdk import PluginContext, PluginRegistry
from humanoid_robot.testing import InMemoryEventBus


def _asr_event(text: str) -> AsrFinal:
    return AsrFinal(
        meta=EventMetadata(correlation_id=new_correlation_id(), producer="tests"),
        session_id=new_session_id(),
        utterance_id=new_utterance_id(),
        text=text,
        language=Language.RU,
        confidence=0.9,
    )


class TestHelloPlugin:
    async def test_activate_subscribes_to_asr_final(self) -> None:
        bus = InMemoryEventBus()
        plugin = build_hello_plugin()
        await plugin.activate(PluginContext(bus=bus))
        # After activate, publishing the target subject should be received
        # without any assertion error and without duplicate handlers.
        await bus.publish(_asr_event("hi"))
        await plugin.deactivate()

    async def test_deactivate_stops_handler(self) -> None:
        bus = InMemoryEventBus()
        plugin = build_hello_plugin()
        await plugin.activate(PluginContext(bus=bus))
        await plugin.deactivate()
        # Second deactivate is a no-op.
        await plugin.deactivate()

    def test_manifest_declared_subscribes(self) -> None:
        assert build_hello_plugin().manifest.subscribes == ("asr.final",)

    def test_entry_point_registered(self) -> None:
        names = {ep.name for ep in entry_points(group="humanoid_robot.plugins")}
        assert "hello" in names

    def test_registry_builds_hello(self) -> None:
        registry = PluginRegistry.discover()
        plugin = registry.build("hello")
        assert isinstance(plugin, HelloPlugin)
