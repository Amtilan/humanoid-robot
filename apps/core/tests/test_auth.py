"""Tests for the bearer-auth middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from humanoid_robot.core.api import router as api_router
from humanoid_robot.core.api.auth import BearerAuthMiddleware, enforce_ws_token
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import AuthSettings, CoreSettings
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.testing import InMemoryEventBus


def _make_app(token: str = "") -> FastAPI:
    settings = CoreSettings(auth=AuthSettings(token=token))
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

    app = FastAPI(lifespan=_lifespan)
    if token:
        app.add_middleware(BearerAuthMiddleware, token=token)
    app.include_router(api_router, prefix="/api/v1")
    return app


class TestBearerAuth:
    def test_no_token_configured_leaves_api_open(self) -> None:
        app = _make_app(token="")
        with TestClient(app) as client:
            resp = client.get("/api/v1/system/info")
        assert resp.status_code == 200

    def test_missing_header_returns_401(self) -> None:
        app = _make_app(token="s3cret")  # noqa: S106
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/groups")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "missing or invalid bearer token"
        assert resp.headers["www-authenticate"].startswith("Bearer")

    def test_valid_bearer_header_passes(self) -> None:
        app = _make_app(token="s3cret")  # noqa: S106
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer s3cret"},
            )
        assert resp.status_code == 200

    def test_query_token_passes(self) -> None:
        app = _make_app(token="s3cret")  # noqa: S106
        with TestClient(app) as client:
            resp = client.get("/api/v1/adapters/groups?token=s3cret")
        assert resp.status_code == 200

    def test_wrong_token_returns_401(self) -> None:
        app = _make_app(token="s3cret")  # noqa: S106
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer other"},
            )
        assert resp.status_code == 401

    def test_health_endpoints_never_require_auth(self) -> None:
        app = _make_app(token="s3cret")  # noqa: S106
        with TestClient(app) as client:
            for path in (
                "/api/v1/system/health/live",
                "/api/v1/system/health/ready",
                "/api/v1/system/info",
            ):
                resp = client.get(path)
                assert resp.status_code == 200, path


class TestWsHelper:
    def test_empty_expected_always_allows(self) -> None:
        assert enforce_ws_token("", header=None, query_token=None) is True

    def test_header_bearer_allowed(self) -> None:
        assert enforce_ws_token("t", header="Bearer t", query_token=None) is True

    def test_query_token_allowed(self) -> None:
        assert enforce_ws_token("t", header=None, query_token="t") is True  # noqa: S106

    def test_wrong_token_rejected(self) -> None:
        assert enforce_ws_token("t", header="Bearer x", query_token=None) is False

    def test_missing_both_rejected(self) -> None:
        assert enforce_ws_token("t", header=None, query_token=None) is False

    def test_non_bearer_scheme_rejected(self) -> None:
        assert enforce_ws_token("t", header="Basic t", query_token=None) is False
