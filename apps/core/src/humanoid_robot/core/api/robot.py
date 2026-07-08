"""Robot manifest endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.robot_manifest_cache import RobotManifestSnapshot

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
