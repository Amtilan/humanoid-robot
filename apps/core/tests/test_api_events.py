"""WebSocket /api/v1/events/ws bridge tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from humanoid_robot.core.api import router as api_router
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import CoreSettings
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import BaseEvent
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.testing import InMemoryEventBus


class _PingEvent(BaseEvent):
    subject: ClassVar[str] = "test.ping"
    schema_version: ClassVar[int] = 1

    payload: str


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def app(bus: InMemoryEventBus) -> FastAPI:
    settings = CoreSettings()
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


class TestEventsWebSocket:
    def test_forwards_published_event_to_client(self, app: FastAPI, bus: InMemoryEventBus) -> None:
        import asyncio

        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/events/ws?subject=test.>") as ws,
        ):
            # Publish an event on the bus — the WebSocket should forward it.
            event = _PingEvent(
                meta=EventMetadata(
                    correlation_id=new_correlation_id(),
                    producer="tests",
                ),
                payload="hello",
            )
            asyncio.run(bus.publish(event))

            raw = ws.receive_text()
            payload = json.loads(raw)
            assert payload["subject"] == "test.ping"
            assert payload["data"]["payload"] == "hello"
            assert payload["producer"] == "tests"
