"""Adapter runtime: load, start, publish, wait, stop."""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotAdapterReady, SystemShuttingDown
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import get_logger
from humanoid_robot.plugins_sdk import AdapterRegistry
from humanoid_robot.ports import EventBusPort, RobotAdapterPort
from humanoid_robot.robot_adapter_app.settings import RobotAdapterSettings

_LOG = get_logger("cortex-robot-adapter")


@dataclass(slots=True)
class AdapterRunner:
    settings: RobotAdapterSettings
    registry: AdapterRegistry = field(default_factory=AdapterRegistry.discover)
    _adapter: RobotAdapterPort | None = None
    _bus: EventBusPort | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        try:
            await self._start()
            await self._stop.wait()
        finally:
            await self._teardown()

    async def _start(self) -> None:
        _LOG.info("adapter_runner.starting", adapter=self.settings.adapter_name)

        # Bus first — adapters publish RobotAdapterReady into it.
        bus = NatsEventBus(
            config=NatsEventBusConfig(
                servers=self.settings.nats.servers,
                name=self.settings.nats.client_name,
                connect_timeout_s=self.settings.nats.connect_timeout_s,
                reconnect_time_wait_s=self.settings.nats.reconnect_time_wait_s,
                max_reconnect_attempts=self.settings.nats.max_reconnect_attempts,
            )
        )
        await bus.connect()
        self._bus = bus

        adapter = self.registry.build(self.settings.adapter_name, **self.settings.adapter_config)
        await adapter.start()
        self._adapter = adapter

        await bus.publish(
            RobotAdapterReady(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer=self.settings.service_name,
                ),
                adapter_name=adapter.manifest.adapter_name,
                adapter_version=adapter.manifest.adapter_version,
                robot_model=adapter.manifest.robot_model,
                capabilities=adapter.capabilities,
            )
        )
        _LOG.info("adapter_runner.ready", adapter=adapter.manifest.adapter_name)

    async def _teardown(self) -> None:
        _LOG.info("adapter_runner.shutting_down")
        if self._bus is not None:
            try:
                await self._bus.publish(
                    SystemShuttingDown(
                        meta=EventMetadata(
                            correlation_id=new_correlation_id(),
                            producer=self.settings.service_name,
                        ),
                        reason="requested",
                    )
                )
            except Exception:
                _LOG.exception("failed to publish shutdown event")
        if self._adapter is not None:
            try:
                await self._adapter.stop()
            except Exception:
                _LOG.exception("adapter stop raised")
        if self._bus is not None:
            try:
                await self._bus.close()
            except Exception:
                _LOG.exception("bus close raised")


async def run_until_signal(settings: RobotAdapterSettings) -> None:
    """Convenience wrapper — installs SIGTERM/SIGINT handlers, then runs."""
    runner = AdapterRunner(settings=settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_stop)
    await runner.run()
