"""Plugin API endpoint tests."""

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
from humanoid_robot.plugins_sdk import (
    PluginContext,
    PluginEntry,
    PluginManifest,
    PluginRegistry,
)
from humanoid_robot.testing import InMemoryEventBus


class _StubPlugin:
    def __init__(self) -> None:
        self._manifest = PluginManifest(name="alpha", version="0.1.0")

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    async def activate(self, _ctx: PluginContext) -> None:
        return

    async def deactivate(self) -> None:
        return


def _stub_factory(**_kwargs: object) -> _StubPlugin:
    return _StubPlugin()


@pytest.fixture
def app() -> FastAPI:
    settings = CoreSettings()
    metrics_registry = CollectorRegistry()
    bus = InMemoryEventBus()
    plugin_registry = PluginRegistry.from_entries(
        [
            PluginEntry(
                name="alpha",
                factory=_stub_factory,
                distribution="stub",
                version="0.1.0",
            )
        ]
    )
    plugin_manager = PluginManager(registry=plugin_registry, bus=bus)
    container = AppContainer(
        settings=settings,
        event_bus=bus,
        metrics_registry=metrics_registry,
        metrics=PromMetrics(registry=metrics_registry),
        plugin_manager=plugin_manager,
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


class TestPluginsApi:
    def test_list_returns_registered_plugins(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/plugins/")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["name"] == "alpha"
        assert body[0]["is_active"] is False

    def test_activate_flips_state_and_returns_manifest(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/v1/plugins/alpha/activate")
            assert resp.status_code == 200
            body = resp.json()
            assert body["is_active"] is True
            assert body["manifest"]["name"] == "alpha"

    def test_deactivate_flips_state(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            client.post("/api/v1/plugins/alpha/activate")
            resp = client.post("/api/v1/plugins/alpha/deactivate")
            assert resp.status_code == 200
            assert resp.json()["is_active"] is False

    def test_activate_unknown_returns_404(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/v1/plugins/nonexistent/activate")
        assert resp.status_code == 404

    def test_double_activate_returns_409(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            client.post("/api/v1/plugins/alpha/activate")
            resp = client.post("/api/v1/plugins/alpha/activate")
        assert resp.status_code == 409
