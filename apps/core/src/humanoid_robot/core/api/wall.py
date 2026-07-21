"""Video-wall manual control — the operator's section remote.

Publishes ``WallCommandRequested`` on the bus; the ``WallCommandRelay``
executes it against the wall agent and publishes the result, which the
dashboard picks up over the WS event stream (same pattern as robot
commands).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.domain.wall import (
    WallCommand,
    WallCommandKind,
    WallNavAction,
    WallSection,
)
from humanoid_robot.events import WallCommandRequested
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


class WallCommandRequest(BaseModel):
    """One wall command from the operator UI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: WallCommandKind
    section: WallSection | None = None
    nav: WallNavAction | None = None
    submitter: str = "operator"


class WallCommandResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    status: str = "requested"


@router.post("/commands", response_model=WallCommandResponse)
async def submit_wall_command(body: WallCommandRequest, request: Request) -> WallCommandResponse:
    container: AppContainer = request.app.state.container
    if container.wall_relay is None:
        # Non-presenter robot: no relay is wired, so a published request
        # would never execute — refuse instead of silently accepting.
        raise HTTPException(status_code=503, detail="wall integration is disabled on this robot")
    command = WallCommand(kind=body.kind, section=body.section, nav=body.nav)
    command_id = str(uuid.uuid4())
    await container.event_bus.publish(
        WallCommandRequested(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.wall",
            ),
            command_id=command_id,
            command=command,
            source=body.submitter,
        )
    )
    return WallCommandResponse(command_id=command_id)


class WallHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    reachable: bool


@router.get("/health", response_model=WallHealthResponse)
async def wall_health(request: Request) -> WallHealthResponse:
    container: AppContainer = request.app.state.container
    if container.wall_client is None:
        return WallHealthResponse(enabled=False, reachable=False)
    return WallHealthResponse(enabled=True, reachable=await container.wall_client.health())
