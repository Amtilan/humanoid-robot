"""Composition root — builds the DI container.

This is the *only* place in the app where concrete adapters are named. Every
other module receives them as constructor parameters or via FastAPI
dependencies routed through here.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Self

from prometheus_client import CollectorRegistry

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import CoreSettings
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.ports import EventBusPort, Subscription


@dataclass(slots=True)
class AppContainer:
    """Singleton-like holder for the app's dependencies.

    Created once by `main.py`; every FastAPI route reads it via
    `app.state.container`.
    """

    settings: CoreSettings
    event_bus: EventBusPort
    metrics_registry: CollectorRegistry
    metrics: PromMetrics
    plugin_manager: PluginManager
    robot_manifest_cache: RobotManifestCache
    _manifest_subscription: Subscription | None = field(default=None)

    @classmethod
    async def create(cls, settings: CoreSettings) -> Self:
        bus = NatsEventBus(
            config=NatsEventBusConfig(
                servers=settings.nats.servers,
                name=settings.nats.client_name,
                connect_timeout_s=settings.nats.connect_timeout_s,
                reconnect_time_wait_s=settings.nats.reconnect_time_wait_s,
                max_reconnect_attempts=settings.nats.max_reconnect_attempts,
                user_credentials=settings.nats.user_credentials,
                tls_ca=settings.nats.tls_ca,
                tls_cert=settings.nats.tls_cert,
                tls_key=settings.nats.tls_key,
            )
        )
        await bus.connect()

        registry = CollectorRegistry()
        metrics = PromMetrics(registry=registry)

        plugin_registry = PluginRegistry.discover()
        plugin_manager = PluginManager(registry=plugin_registry, bus=bus)

        manifest_cache = RobotManifestCache()
        manifest_subscription = await manifest_cache.start(bus)

        return cls(
            settings=settings,
            event_bus=bus,
            metrics_registry=registry,
            metrics=metrics,
            plugin_manager=plugin_manager,
            robot_manifest_cache=manifest_cache,
            _manifest_subscription=manifest_subscription,
        )

    async def close(self) -> None:
        """Release resources; safe to call multiple times."""
        await self.plugin_manager.deactivate_all()
        if self._manifest_subscription is not None:
            with contextlib.suppress(Exception):
                await self._manifest_subscription.cancel()
            self._manifest_subscription = None
        await self.event_bus.close()
