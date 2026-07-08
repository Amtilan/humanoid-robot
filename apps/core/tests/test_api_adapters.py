"""Tests for /api/v1/adapters."""

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
    registry = CollectorRegistry()
    bus = InMemoryEventBus()
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


class TestAdaptersApi:
    def test_groups_returns_known_list(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/groups")
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        # Every group we care about is exposed.
        for expected in [
            "humanoid_robot.robot_adapters",
            "humanoid_robot.audio_in_adapters",
            "humanoid_robot.llm_adapters",
            "humanoid_robot.plugins",
        ]:
            assert expected in groups

    def test_group_lists_installed_adapters(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/humanoid_robot.audio_in_adapters")
        assert resp.status_code == 200
        body = resp.json()
        names = [e["name"] for e in body["entries"]]
        # From the audio-null + audio-alsa + unitree-g1 packages.
        assert {"alsa", "null", "unitree_g1"} <= set(names)

    def test_unknown_group_returns_404(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/humanoid_robot.nonexistent")
        assert resp.status_code == 404

    def test_plugin_group_lists_hello(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/humanoid_robot.plugins")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()["entries"]]
        assert "hello" in names
