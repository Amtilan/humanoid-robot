"""Knowledge-base management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.knowledge_service import (
    IngestJobStatus,
    KnowledgeNotConfiguredError,
)
from humanoid_robot.ports import KnowledgeSourceSummary

router = APIRouter()


class KnowledgeStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    configured: bool
    sources: list[KnowledgeSourceSummary] = Field(default_factory=list)


class IngestJobRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    directory: str = Field(min_length=1)
    config_path: str = Field(min_length=1)


@router.get("/status", response_model=KnowledgeStatusResponse)
async def status(request: Request) -> KnowledgeStatusResponse:
    container: AppContainer = request.app.state.container
    service = container.knowledge_service
    if not service.is_configured():
        return KnowledgeStatusResponse(configured=False, sources=[])
    sources = await service.list_sources()
    return KnowledgeStatusResponse(configured=True, sources=list(sources))


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: str, request: Request) -> None:
    container: AppContainer = request.app.state.container
    try:
        await container.knowledge_service.delete_source(source_id)
    except KnowledgeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ingest-jobs", response_model=IngestJobStatus)
async def start_ingest_job(body: IngestJobRequest, request: Request) -> IngestJobStatus:
    container: AppContainer = request.app.state.container
    return await container.knowledge_service.start_ingest_job(
        directory=body.directory,
        config_path=body.config_path,
    )


@router.get("/ingest-jobs", response_model=list[IngestJobStatus])
async def list_ingest_jobs(request: Request) -> list[IngestJobStatus]:
    container: AppContainer = request.app.state.container
    return container.knowledge_service.jobs()


@router.get("/ingest-jobs/{job_id}", response_model=IngestJobStatus)
async def get_ingest_job(job_id: str, request: Request) -> IngestJobStatus:
    container: AppContainer = request.app.state.container
    job = container.knowledge_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return job
