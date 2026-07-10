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
from humanoid_robot.ports import (
    ArmPort,
    BatteryPort,
    EventBusPort,
    HandPort,
    HeadPort,
    LocomotionPort,
    PosturePort,
    RobotAdapterPort,
)
from humanoid_robot.robot_adapter_app.dispatcher import CommandDispatcher
from humanoid_robot.robot_adapter_app.settings import RobotAdapterSettings
from humanoid_robot.robot_adapter_app.telemetry_pump import (
    TelemetryPump,
    battery_source,
    imu_source,
    temperature_source,
)


def _resolve_locomotion(adapter: RobotAdapterPort) -> LocomotionPort | None:
    """Prefer an explicit `.locomotion` sub-adapter over duck-typing on root.

    Duck-typing the root would match the lifecycle `stop()` and the
    LocomotionPort `stop(cmd)` at the same name — dispatching a StopCommand
    would then reach the lifecycle method.  Sub-adapter keeps them separated.
    """
    sub = getattr(adapter, "locomotion", None)
    if sub is not None and isinstance(sub, LocomotionPort):
        return sub
    return None


def _resolve_arm(adapter: RobotAdapterPort) -> ArmPort | None:
    sub = getattr(adapter, "arm", None)
    if sub is not None and isinstance(sub, ArmPort):
        return sub
    return None


def _resolve_head(adapter: RobotAdapterPort) -> HeadPort | None:
    sub = getattr(adapter, "head", None)
    if sub is not None and isinstance(sub, HeadPort):
        return sub
    return None


def _resolve_posture(adapter: RobotAdapterPort) -> PosturePort | None:
    sub = getattr(adapter, "posture", None)
    if sub is not None and isinstance(sub, PosturePort):
        return sub
    return None


def _resolve_hand(adapter: RobotAdapterPort) -> HandPort | None:
    sub = getattr(adapter, "hand", None)
    if sub is not None and isinstance(sub, HandPort):
        return sub
    return None


def _resolve_battery(adapter: RobotAdapterPort) -> BatteryPort | None:
    sub = getattr(adapter, "battery", None)
    if sub is not None and isinstance(sub, BatteryPort):
        return sub
    return None


_LOG = get_logger("cortex-robot-adapter")


@dataclass(slots=True)
class AdapterRunner:
    settings: RobotAdapterSettings
    registry: AdapterRegistry = field(default_factory=AdapterRegistry.discover)
    _adapter: RobotAdapterPort | None = None
    _bus: EventBusPort | None = None
    _dispatcher: CommandDispatcher | None = None
    _telemetry: TelemetryPump | None = None
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

        dispatcher = CommandDispatcher(bus=bus, producer=self.settings.service_name)
        locomotion = _resolve_locomotion(adapter)
        if locomotion is not None:
            dispatcher.register_locomotion(locomotion)
        posture = _resolve_posture(adapter)
        if posture is not None:
            dispatcher.register_posture(posture)
        arm = _resolve_arm(adapter)
        if arm is not None:
            dispatcher.register_arm(arm)
        head = _resolve_head(adapter)
        if head is not None:
            dispatcher.register_head(head)
        hand = _resolve_hand(adapter)
        if hand is not None:
            dispatcher.register_hand(hand)
        await dispatcher.start()
        self._dispatcher = dispatcher

        telemetry = TelemetryPump(
            bus=bus,
            interval_s=self.settings.telemetry_interval_s,
            producer=self.settings.service_name,
        )
        battery = _resolve_battery(adapter)
        if battery is not None:
            telemetry.register(battery_source(battery))
        imu = getattr(adapter, "imu", None)
        if imu is not None and hasattr(imu, "read"):
            telemetry.register(imu_source(imu))
        temperature = getattr(adapter, "temperature", None)
        if temperature is not None and hasattr(temperature, "read"):
            telemetry.register(temperature_source(temperature))
        await telemetry.start()
        self._telemetry = telemetry

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
        _LOG.info(
            "adapter_runner.ready",
            adapter=adapter.manifest.adapter_name,
            capabilities=sorted(dispatcher.handlers.keys()),
        )

    async def _teardown(self) -> None:
        _LOG.info("adapter_runner.shutting_down")
        await self._teardown_workers()
        await self._teardown_bus_and_adapter()

    async def _teardown_workers(self) -> None:
        if self._telemetry is not None:
            try:
                await self._telemetry.stop()
            except Exception:
                _LOG.exception("telemetry stop raised")
        if self._dispatcher is not None:
            try:
                await self._dispatcher.stop()
            except Exception:
                _LOG.exception("dispatcher stop raised")

    async def _teardown_bus_and_adapter(self) -> None:
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
