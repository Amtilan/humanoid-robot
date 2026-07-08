"""Adapter introspection endpoints — list installed adapters by group."""

from __future__ import annotations

from importlib.metadata import entry_points

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_KNOWN_GROUPS: tuple[str, ...] = (
    "humanoid_robot.robot_adapters",
    "humanoid_robot.audio_in_adapters",
    "humanoid_robot.audio_out_adapters",
    "humanoid_robot.vad_adapters",
    "humanoid_robot.wakeword_adapters",
    "humanoid_robot.asr_adapters",
    "humanoid_robot.tts_adapters",
    "humanoid_robot.llm_adapters",
    "humanoid_robot.embedding_adapters",
    "humanoid_robot.reranker_adapters",
    "humanoid_robot.vector_adapters",
    "humanoid_robot.parser_adapters",
    "humanoid_robot.chunker_adapters",
    "humanoid_robot.plugins",
)


class AdapterEntryInfo(BaseModel):
    name: str
    distribution: str | None
    version: str | None
    target: str


class AdapterListResponse(BaseModel):
    group: str
    entries: list[AdapterEntryInfo]


class AdapterGroupsResponse(BaseModel):
    groups: list[str]


@router.get("/groups", response_model=AdapterGroupsResponse)
async def list_groups() -> AdapterGroupsResponse:
    return AdapterGroupsResponse(groups=list(_KNOWN_GROUPS))


@router.get("/{group}", response_model=AdapterListResponse)
async def list_adapters(group: str) -> AdapterListResponse:
    if group not in _KNOWN_GROUPS:
        raise HTTPException(status_code=404, detail=f"unknown group {group!r}")
    entries = [
        AdapterEntryInfo(
            name=ep.name,
            distribution=ep.dist.name if ep.dist is not None else None,
            version=ep.dist.version if ep.dist is not None else None,
            target=ep.value,
        )
        for ep in entry_points(group=group)
    ]
    entries.sort(key=lambda e: e.name)
    return AdapterListResponse(group=group, entries=entries)
