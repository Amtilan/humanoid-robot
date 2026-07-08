"""HelloPlugin — reference implementation.

Subscribes to `asr.final` and logs the transcript. Nothing else. Kept
deliberately minimal — third-party plugins should use it as a starting
point for how to plumb their business logic through the platform's event
bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from humanoid_robot.events import AsrFinal, BaseEvent
from humanoid_robot.observability import get_logger
from humanoid_robot.plugins_sdk import (
    PluginContext,
    PluginManifest,
    PluginPort,
)
from humanoid_robot.ports import Subscription

_LOG = get_logger("plugin.hello")

_MANIFEST = PluginManifest(
    name="hello",
    version="0.0.0",
    description="Reference first-party plugin — logs on every asr.final event.",
    author="humanoid-robot contributors",
    permissions=(),
    subscribes=(AsrFinal.subject,),
)


@dataclass(slots=True)
class HelloPlugin(PluginPort):
    """Emits a log line for every transcribed utterance."""

    _subscription: Subscription | None = field(default=None, init=False)

    @property
    def manifest(self) -> PluginManifest:
        return _MANIFEST

    async def activate(self, context: PluginContext) -> None:
        self._subscription = await context.bus.subscribe(AsrFinal.subject, self._on_asr_final)
        _LOG.info("plugin.hello.activated")

    async def deactivate(self) -> None:
        if self._subscription is not None:
            await self._subscription.cancel()
            self._subscription = None
        _LOG.info("plugin.hello.deactivated")

    async def _on_asr_final(self, event: BaseEvent) -> None:
        if not isinstance(event, AsrFinal):
            return
        _LOG.info(
            "plugin.hello.heard",
            session_id=event.session_id,
            text=event.text,
            language=event.language.value,
        )


def build_hello_plugin(**_kwargs: object) -> HelloPlugin:
    """Entry-point factory."""
    return HelloPlugin()
