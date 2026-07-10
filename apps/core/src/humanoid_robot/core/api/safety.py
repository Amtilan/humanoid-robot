"""Safety endpoints — status + e-stop controls."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import SafetyWatchdogHeartbeat
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.safety import AuditRecord

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
    command_timeout_s: float
    pending_command_count: int
    pending_command_ids: list[str]
    max_linear_speed_mps: float
    max_angular_rate_rps: float


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
    reconciler = container.safety_reconciler
    pending_count = reconciler.pending_count() if reconciler is not None else 0
    pending_ids = list(reconciler.pending_ids()) if reconciler is not None else []
    return SafetyStatus(
        estop_engaged=engaged,
        allowed_capabilities=list(settings.allowed_capabilities),
        rate_limit_window_s=settings.rate_limit_window_s,
        rate_limit_max_events=settings.rate_limit_max_events,
        watchdog_timeout_s=settings.watchdog_timeout_s,
        watchdog_live=watchdog_live,
        watchdog_seconds_since_heartbeat=seconds_since,
        command_timeout_s=settings.command_timeout_s,
        pending_command_count=pending_count,
        pending_command_ids=pending_ids,
        max_linear_speed_mps=settings.max_linear_speed_mps,
        max_angular_rate_rps=settings.max_angular_rate_rps,
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


class AuditResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    records: list[AuditRecord]


@router.get("/audit", response_model=AuditResponse)
async def audit(
    request: Request,
    subject_prefix: str | None = Query(default=None, max_length=64),
    since_iso: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=1000),
) -> AuditResponse:
    container: AppContainer = request.app.state.container
    if container.safety_audit is None:
        raise HTTPException(status_code=503, detail="audit recorder not initialised")
    records = await container.safety_audit.query(
        subject_prefix=subject_prefix, since_iso=since_iso, limit=limit
    )
    total = await container.safety_audit.count()
    return AuditResponse(total=total, records=list(records))


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
