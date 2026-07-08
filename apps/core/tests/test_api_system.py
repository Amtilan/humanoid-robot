"""Tests for the /api/v1/system endpoints using an in-memory event bus."""

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
from humanoid_robot.testing import InMemoryEventBus


@pytest.fixture
def app() -> FastAPI:
    settings = CoreSettings()
    bus = InMemoryEventBus()
    registry = CollectorRegistry()
    container = AppContainer(
        settings=settings,
        event_bus=bus,
        metrics_registry=registry,
        metrics=PromMetrics(registry=registry),
        plugin_manager=PluginManager(registry=PluginRegistry.from_entries([]), bus=bus),
        robot_manifest_cache=RobotManifestCache(),
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


class TestSystemApi:
    def test_info_returns_defaults(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/system/info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "cortex-core"
        assert body["environment"] == "prod"

    def test_liveness(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/system/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readiness(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/system/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}
