"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from humanoid_robot.core.api import router as api_router
from humanoid_robot.core.api.auth import BearerAuthMiddleware
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.settings import CoreSettings
from humanoid_robot.observability import (
    configure_logging,
    configure_tracing,
    get_logger,
)


def create_app(settings: CoreSettings) -> FastAPI:
    """Build the FastAPI app with the given settings."""

    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.observability.log_level,
    )
    configure_tracing(
        service=settings.service_name,
        environment=settings.environment,
        otlp_endpoint=settings.observability.otlp_endpoint,
        enabled=settings.observability.tracing_enabled,
    )
    log = get_logger("cortex-core")

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("cortex-core.starting", version="0.0.0")
        container = await AppContainer.create(settings)
        app.state.container = container
        try:
            log.info("cortex-core.ready")
            yield
        finally:
            log.info("cortex-core.shutting_down")
            await container.close()

    app = FastAPI(
        title="cortex-core",
        version="0.0.0",
        lifespan=_lifespan,
        # openapi is enabled by default; we override tag descriptions.
        openapi_tags=[{"name": "system", "description": "Health and metadata."}],
    )
    if settings.auth.token:
        app.add_middleware(BearerAuthMiddleware, token=settings.auth.token)
        log.info("cortex-core.auth_enabled")
    app.include_router(api_router, prefix="/api/v1")
    _mount_metrics(app)
    return app


def _mount_metrics(app: FastAPI) -> None:
    """Serve `/metrics` from the container's registry.

    We wire this here rather than in a router because the metrics endpoint
    must not go through routers that log every request.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.requests import Request
    from starlette.responses import Response

    async def _metrics(request: Request) -> Response:
        container: AppContainer = request.app.state.container
        payload = generate_latest(container.metrics_registry)
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)

    app.add_route("/metrics", _metrics, methods=["GET"], include_in_schema=False)


# Uvicorn workers can import `humanoid_robot.core.app:app_from_env` and get a
# ready-to-serve app. We wrap the factory so it is discoverable.
def app_from_env() -> FastAPI:  # pragma: no cover
    from humanoid_robot.core.settings import load_settings

    return create_app(load_settings())
