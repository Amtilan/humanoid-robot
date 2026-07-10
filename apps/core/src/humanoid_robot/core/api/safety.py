"""Safety endpoints — status + e-stop controls."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import SafetyWatchdogHeartbeat
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


class SafetyStatus(BaseModel):
    """Current safety gate state (read-model)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    estop_engaged: bool
    allowed_capabilities: list[str]
    rate_limit_window_s: float
    rate_limit_max_events: int
    watchdog_timeout_s: float
    watchdog_live: bool
    watchdog_seconds_since_heartbeat: float | None


class EStopRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=200)


class EStopResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engaged: bool
    changed: bool


@router.get("/status", response_model=SafetyStatus)
async def status(request: Request) -> SafetyStatus:
    container: AppContainer = request.app.state.container
    if container.safety_gate is None:
        raise HTTPException(status_code=503, detail="safety gate not initialised")
    engaged = await container.safety_gate.estop.engaged()
    settings = container.settings.safety
    watchdog = container.safety_watchdog
    watchdog_live = False
    seconds_since = None
    if watchdog is not None:
        watchdog_live = await watchdog.is_live()
        seconds_since = await watchdog.seconds_since_heartbeat()
    return SafetyStatus(
        estop_engaged=engaged,
        allowed_capabilities=list(settings.allowed_capabilities),
        rate_limit_window_s=settings.rate_limit_window_s,
        rate_limit_max_events=settings.rate_limit_max_events,
        watchdog_timeout_s=settings.watchdog_timeout_s,
        watchdog_live=watchdog_live,
        watchdog_seconds_since_heartbeat=seconds_since,
    )


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1, max_length=64)


class HeartbeatResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool


@router.post("/watchdog/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(body: HeartbeatRequest, request: Request) -> HeartbeatResponse:
    container: AppContainer = request.app.state.container
    await container.event_bus.publish(
        SafetyWatchdogHeartbeat(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.safety_api",
            ),
            actor=body.actor,
        )
    )
    return HeartbeatResponse(accepted=True)


@router.post("/estop/engage", response_model=EStopResponse)
async def engage(body: EStopRequest, request: Request) -> EStopResponse:
    container: AppContainer = request.app.state.container
    if container.safety_gate is None:
        raise HTTPException(status_code=503, detail="safety gate not initialised")
    changed = await container.safety_gate.engage_estop(actor=body.actor, reason=body.reason)
    return EStopResponse(engaged=True, changed=changed)


@router.post("/estop/release", response_model=EStopResponse)
async def release(body: EStopRequest, request: Request) -> EStopResponse:
    container: AppContainer = request.app.state.container
    if container.safety_gate is None:
        raise HTTPException(status_code=503, detail="safety gate not initialised")
    changed = await container.safety_gate.release_estop(actor=body.actor)
    return EStopResponse(engaged=False, changed=changed)
