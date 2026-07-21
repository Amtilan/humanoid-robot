"""Dialogue history API — the chat panel seeds itself from here on load."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query

from humanoid_robot.core.dialogue_journal import clear_sync, list_messages_sync

router = APIRouter()


@router.get("")
async def list_messages(limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    records = await asyncio.to_thread(list_messages_sync, limit)
    return {"records": records}


@router.delete("")
async def clear() -> dict[str, Any]:
    deleted = await asyncio.to_thread(clear_sync)
    return {"deleted": deleted}
