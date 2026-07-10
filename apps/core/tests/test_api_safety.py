"""Tests for /api/v1/safety endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from humanoid_robot.core.api import router as api_router
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import CoreSettings
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.safety import (
    ChainPolicy,
    EStopPolicy,
    EStopState,
    KnownCapabilitiesPolicy,
    SafetyGate,
)
from humanoid_robot.testing import InMemoryEventBus


@pytest.fixture
def app() -> FastAPI:
    settings = CoreSettings()
    bus = InMemoryEventBus()
    registry = CollectorRegistry()
    estop = EStopState(engaged=True)
    gate = SafetyGate(
        policy=ChainPolicy(
            [
                KnownCapabilitiesPolicy(allowed=frozenset(settings.safety.allowed_capabilities)),
                EStopPolicy(estop),
            ]
        ),
        bus=bus,
        estop=estop,
    )
    container = AppContainer(
        settings=settings,
        event_bus=bus,
        metrics_registry=registry,
        metrics=PromMetrics(registry=registry),
        plugin_manager=PluginManager(registry=PluginRegistry.from_entries([]), bus=bus),
        robot_manifest_cache=RobotManifestCache(),
        safety_gate=gate,
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        try:
            yield
        finally:
            await container.close()

    fastapi_app = FastAPI(lifespan=_lifespan)
    fastapi_app.include_router(api_router, prefix="/api/v1")
    return fastapi_app


class TestSafetyApi:
    def test_status_reports_engaged_by_default(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/safety/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["estop_engaged"] is True
        assert "locomotion.move" in body["allowed_capabilities"]

    def test_release_then_engage(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            release = client.post(
                "/api/v1/safety/estop/release",
                json={"actor": "test-operator"},
            )
            assert release.status_code == 200
            assert release.json()["engaged"] is False
            assert release.json()["changed"] is True

            engage = client.post(
                "/api/v1/safety/estop/engage",
                json={"actor": "test-operator", "reason": "unit test"},
            )
            assert engage.status_code == 200
            assert engage.json()["engaged"] is True
            assert engage.json()["changed"] is True

            engage_again = client.post(
                "/api/v1/safety/estop/engage",
                json={"actor": "test-operator"},
            )
            assert engage_again.json()["changed"] is False

    def test_engage_rejects_empty_actor(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/v1/safety/estop/engage", json={"actor": ""})
        assert resp.status_code == 422
