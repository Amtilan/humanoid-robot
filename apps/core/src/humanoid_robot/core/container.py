"""Composition root — builds the DI container.

This is the *only* place in the app where concrete adapters are named. Every
other module receives them as constructor parameters or via FastAPI
dependencies routed through here.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Self

from prometheus_client import CollectorRegistry

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.core.diagnostics_ticker import DiagnosticsTicker
from humanoid_robot.core.knowledge_service import KnowledgeService
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import CoreSettings
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.safety import (
    ActorRateLimit,
    ChainPolicy,
    CommandReconciler,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    PayloadSchemaPolicy,
    PerActorRateLimitPolicy,
    RateLimitPolicy,
    SafetyAuditRecorder,
    SafetyGate,
    SafetyWatchdog,
    VelocityLimitPolicy,
)


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
    knowledge_service: KnowledgeService = field(default_factory=KnowledgeService)
    diagnostics_ticker: DiagnosticsTicker | None = field(default=None)
    safety_gate: SafetyGate | None = field(default=None)
    safety_task: asyncio.Task[None] | None = field(default=None)
    safety_watchdog: SafetyWatchdog | None = field(default=None)
    safety_reconciler: CommandReconciler | None = field(default=None)
    safety_audit: SafetyAuditRecorder | None = field(default=None)
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

        diagnostics_ticker = DiagnosticsTicker(bus=bus)
        await diagnostics_ticker.start()

        estop = EStopState(engaged=True)
        actor_limits = {
            name: ActorRateLimit(window_s=budget.window_s, max_events=budget.max_events)
            for name, budget in settings.safety.actor_budgets.items()
        }
        safety_policy = ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset(settings.safety.allowed_capabilities)),
                PayloadSchemaPolicy(),
                VelocityLimitPolicy(
                    max_linear_speed_mps=settings.safety.max_linear_speed_mps,
                    max_angular_rate_rps=settings.safety.max_angular_rate_rps,
                ),
                PerActorRateLimitPolicy(
                    limits=actor_limits,
                    default=ActorRateLimit(
                        window_s=settings.safety.actor_default_budget.window_s,
                        max_events=settings.safety.actor_default_budget.max_events,
                    ),
                ),
                RateLimitPolicy(
                    window_s=settings.safety.rate_limit_window_s,
                    max_events=settings.safety.rate_limit_max_events,
                ),
                EStopPolicy(estop),
            ]
        )
        safety_gate = SafetyGate(policy=safety_policy, bus=bus, estop=estop)
        safety_task = asyncio.create_task(safety_gate.run(), name="safety-gate")

        safety_watchdog = SafetyWatchdog(
            gate=safety_gate,
            bus=bus,
            timeout_s=settings.safety.watchdog_timeout_s,
            check_interval_s=settings.safety.watchdog_check_interval_s,
        )
        await safety_watchdog.start()

        safety_reconciler = CommandReconciler(
            gate=safety_gate,
            bus=bus,
            timeout_s=settings.safety.command_timeout_s,
            check_interval_s=settings.safety.command_check_interval_s,
        )
        await safety_reconciler.start()

        safety_audit = SafetyAuditRecorder(bus=bus, db_path=settings.safety.audit_db_path)
        await safety_audit.start()

        return cls(
            settings=settings,
            event_bus=bus,
            metrics_registry=registry,
            metrics=metrics,
            plugin_manager=plugin_manager,
            robot_manifest_cache=manifest_cache,
            knowledge_service=KnowledgeService(),
            diagnostics_ticker=diagnostics_ticker,
            safety_gate=safety_gate,
            safety_task=safety_task,
            safety_watchdog=safety_watchdog,
            safety_reconciler=safety_reconciler,
            safety_audit=safety_audit,
            _manifest_subscription=manifest_subscription,
        )

    async def close(self) -> None:
        """Release resources; safe to call multiple times."""
        await self.plugin_manager.deactivate_all()
        if self.diagnostics_ticker is not None:
            await self.diagnostics_ticker.stop()
            self.diagnostics_ticker = None
        if self.safety_audit is not None:
            await self.safety_audit.stop()
            self.safety_audit = None
        if self.safety_reconciler is not None:
            await self.safety_reconciler.stop()
            self.safety_reconciler = None
        if self.safety_watchdog is not None:
            await self.safety_watchdog.stop()
            self.safety_watchdog = None
        if self.safety_gate is not None:
            self.safety_gate.request_stop()
        if self.safety_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.safety_task
            self.safety_task = None
        self.safety_gate = None
        if self._manifest_subscription is not None:
            with contextlib.suppress(Exception):
                await self._manifest_subscription.cancel()
            self._manifest_subscription = None
        await self.event_bus.close()
