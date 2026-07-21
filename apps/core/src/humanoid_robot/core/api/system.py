"""System endpoints: version, health checks."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from humanoid_robot.core.container import AppContainer

router = APIRouter()


class ServiceInfo(BaseModel):
    service: str
    version: str
    environment: str
    # "guard" | "presenter" | "generic" — the dashboard adapts its tabs.
    role: str = "generic"


class HealthResponse(BaseModel):
    status: str


@router.get("/info", response_model=ServiceInfo)
async def get_info(request: Request) -> ServiceInfo:
    container: AppContainer = request.app.state.container
    return ServiceInfo(
        service=container.settings.service_name,
        version="0.0.0",
        environment=container.settings.environment,
        role=container.settings.role,
    )


@router.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    """Liveness — always returns OK if the process is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def health_ready(request: Request) -> HealthResponse:
    """Readiness — every declared dependency must be alive."""
    container: AppContainer = request.app.state.container
    # For now we only depend on the event bus; more checks added per phase.
    # NatsEventBus does not expose a boolean readiness yet; connect() ran to
    # completion means the client is up. We can extend this later.
    _ = container.event_bus
    return HealthResponse(status="ready")
