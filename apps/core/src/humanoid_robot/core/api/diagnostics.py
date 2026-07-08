"""Diagnostics endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from humanoid_robot.core.diagnostics import (
    GpuStats,
    HostDiagnostics,
    collect_gpu,
    collect_host,
)

router = APIRouter()


@router.get("/host", response_model=HostDiagnostics)
async def get_host() -> HostDiagnostics:
    return collect_host()


@router.get("/gpu", response_model=GpuStats)
async def get_gpu() -> GpuStats:
    return collect_gpu()
