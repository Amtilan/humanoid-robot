"""Plugin lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.plugin_manager import (
    PluginAlreadyActiveError,
    PluginNotActiveError,
    PluginNotFoundError,
    PluginStatus,
)

router = APIRouter()


@router.get("/", response_model=list[PluginStatus])
async def list_plugins(request: Request) -> list[PluginStatus]:
    container: AppContainer = request.app.state.container
    return container.plugin_manager.list_statuses()


@router.post("/{name}/activate", response_model=PluginStatus)
async def activate_plugin(name: str, request: Request) -> PluginStatus:
    container: AppContainer = request.app.state.container
    try:
        return await container.plugin_manager.activate(name)
    except PluginNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PluginAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{name}/deactivate", response_model=PluginStatus)
async def deactivate_plugin(name: str, request: Request) -> PluginStatus:
    container: AppContainer = request.app.state.container
    try:
        return await container.plugin_manager.deactivate(name)
    except PluginNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PluginNotActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
