"""Tests for the /api/v1/diagnostics endpoints."""

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


class TestDiagnosticsApi:
    def test_host_returns_shape(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/diagnostics/host")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cpu"]["core_count"] >= 1
        assert body["memory"]["total_bytes"] > 0
        assert isinstance(body["disks"], list)
        assert body["uptime_s"] > 0

    def test_gpu_returns_supported_flag(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/diagnostics/gpu")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["supported"], bool)
