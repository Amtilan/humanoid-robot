"""Tests for the bearer-auth middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from humanoid_robot.core.api import router as api_router
from humanoid_robot.core.api.auth import (
    BearerAuthMiddleware,
    UnauthAttemptLimiter,
    enforce_ws_token,
)
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.plugin_manager import PluginManager
from humanoid_robot.core.robot_manifest_cache import RobotManifestCache
from humanoid_robot.core.settings import AuthSettings, CoreSettings
from humanoid_robot.observability import PromMetrics
from humanoid_robot.plugins_sdk import PluginRegistry
from humanoid_robot.testing import InMemoryEventBus


def _make_app(
    token: str = "",
    *,
    rate_limiter: UnauthAttemptLimiter | None = None,
) -> FastAPI:
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
        app.add_middleware(BearerAuthMiddleware, token=token, rate_limiter=rate_limiter)
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


class _FakeClock:
    """Deterministic time source for rate-limiter tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class TestUnauthAttemptLimiter:
    def test_allows_below_threshold(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=3, window_s=60.0)
        for _ in range(2):
            limiter.register_failure("client-A")
        blocked, retry = limiter.blocked("client-A")
        assert blocked is False
        assert retry == 0.0

    def test_blocks_at_threshold(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=3, window_s=60.0)
        for _ in range(3):
            limiter.register_failure("client-A")
        blocked, retry = limiter.blocked("client-A")
        assert blocked is True
        assert retry > 0.0

    def test_window_rolls_over(self) -> None:
        clock = _FakeClock()
        limiter = UnauthAttemptLimiter(max_attempts=3, window_s=10.0, time_fn=clock)
        for _ in range(3):
            limiter.register_failure("client-A")
        assert limiter.blocked("client-A")[0] is True
        clock.t = 11.0
        assert limiter.blocked("client-A")[0] is False

    def test_clients_tracked_separately(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=2, window_s=60.0)
        limiter.register_failure("A")
        limiter.register_failure("A")
        assert limiter.blocked("A")[0] is True
        assert limiter.blocked("B")[0] is False

    def test_reset_clears_client(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=2, window_s=60.0)
        limiter.register_failure("A")
        limiter.register_failure("A")
        assert limiter.blocked("A")[0] is True
        limiter.reset("A")
        assert limiter.blocked("A")[0] is False


class TestBearerAuthRateLimit:
    def test_repeated_401s_transition_to_429(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=3, window_s=60.0)
        app = _make_app(token="s3cret", rate_limiter=limiter)  # noqa: S106
        with TestClient(app) as client:
            for _ in range(3):
                resp = client.get(
                    "/api/v1/adapters/groups",
                    headers={"Authorization": "Bearer wrong"},
                )
                assert resp.status_code == 401
            resp = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer wrong"},
            )
            assert resp.status_code == 429
            assert int(resp.headers["retry-after"]) >= 1

    def test_valid_token_after_block_still_429(self) -> None:
        # Blocked clients must not learn 'was that token right?' by
        # observing 429 vs 200.
        limiter = UnauthAttemptLimiter(max_attempts=2, window_s=60.0)
        app = _make_app(token="s3cret", rate_limiter=limiter)  # noqa: S106
        with TestClient(app) as client:
            for _ in range(2):
                client.get(
                    "/api/v1/adapters/groups",
                    headers={"Authorization": "Bearer wrong"},
                )
            resp = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer s3cret"},
            )
            assert resp.status_code == 429

    def test_success_clears_counter(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=3, window_s=60.0)
        app = _make_app(token="s3cret", rate_limiter=limiter)  # noqa: S106
        with TestClient(app) as client:
            for _ in range(2):
                resp = client.get(
                    "/api/v1/adapters/groups",
                    headers={"Authorization": "Bearer wrong"},
                )
                assert resp.status_code == 401
            ok = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer s3cret"},
            )
            assert ok.status_code == 200
            # After the reset, we again get full budget before 429.
            for _ in range(3):
                resp = client.get(
                    "/api/v1/adapters/groups",
                    headers={"Authorization": "Bearer wrong"},
                )
                assert resp.status_code == 401

    def test_health_endpoints_never_count_toward_limit(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=1, window_s=60.0)
        app = _make_app(token="s3cret", rate_limiter=limiter)  # noqa: S106
        with TestClient(app) as client:
            for _ in range(10):
                assert client.get("/api/v1/system/health/ready").status_code == 200
            resp = client.get(
                "/api/v1/adapters/groups",
                headers={"Authorization": "Bearer wrong"},
            )
            assert resp.status_code == 401

    def test_xff_first_hop_used_as_client_key(self) -> None:
        limiter = UnauthAttemptLimiter(max_attempts=2, window_s=60.0)
        app = _make_app(token="s3cret", rate_limiter=limiter)  # noqa: S106
        with TestClient(app) as client:
            for _ in range(2):
                client.get(
                    "/api/v1/adapters/groups",
                    headers={
                        "Authorization": "Bearer wrong",
                        "X-Forwarded-For": "10.0.0.42, 172.16.0.1",
                    },
                )
            attacker = client.get(
                "/api/v1/adapters/groups",
                headers={
                    "Authorization": "Bearer wrong",
                    "X-Forwarded-For": "10.0.0.42",
                },
            )
            assert attacker.status_code == 429
            innocent = client.get(
                "/api/v1/adapters/groups",
                headers={
                    "Authorization": "Bearer wrong",
                    "X-Forwarded-For": "10.0.0.99",
                },
            )
            assert innocent.status_code == 401
