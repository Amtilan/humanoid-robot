"""Robot manifest endpoints + command intake."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.robot_manifest_cache import RobotManifestSnapshot
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotCommandRequested
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


@router.get("/manifests", response_model=list[RobotManifestSnapshot])
async def list_manifests(request: Request) -> list[RobotManifestSnapshot]:
    container: AppContainer = request.app.state.container
    return container.robot_manifest_cache.all()


@router.get("/manifests/{adapter_name}", response_model=RobotManifestSnapshot)
async def get_manifest(adapter_name: str, request: Request) -> RobotManifestSnapshot:
    container: AppContainer = request.app.state.container
    snapshot = container.robot_manifest_cache.get(adapter_name)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"no manifest cached for adapter {adapter_name!r}",
        )
    return snapshot


class RobotCommandBody(BaseModel):
    """Operator-issued command sent through the safety gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    submitter: str = Field(default="operator", min_length=1, max_length=64)


class RobotCommandAck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str


@router.post("/commands", response_model=RobotCommandAck)
async def submit_command(body: RobotCommandBody, request: Request) -> RobotCommandAck:
    """Publish `robot.command.requested`.

    The command flows through the safety gate before the dispatcher can
    execute it; the result is delivered as `robot.command.result` on the
    event bus, which the UI tails via WebSocket.
    """
    container: AppContainer = request.app.state.container
    command_id = f"cmd-{uuid.uuid4().hex[:12]}"
    await container.event_bus.publish(
        RobotCommandRequested(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.robot_api",
            ),
            command_id=command_id,
            capability=body.capability,
            payload=body.payload,
            submitter=body.submitter,
        )
    )
    return RobotCommandAck(command_id=command_id)
