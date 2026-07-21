"""Guard panel API — visitor journal + starting the interview remotely.

Cards are written by `VisitJournal` (bus subscriber); this router reads
the journal, flips card status and lets the panel (or the future
visitor-detection camera) kick off the voice interview.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.visit_journal import list_visits_sync, mark_processed_sync
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import VisitIntakeStart
from humanoid_robot.events.base import EventMetadata

router = APIRouter()


@router.get("")
async def list_visits(
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None, pattern="^(new|processed)$"),
) -> dict[str, Any]:
    records = await asyncio.to_thread(list_visits_sync, limit, status)
    return {"records": records}


@router.post("/{visit_id}/processed")
async def mark_processed(visit_id: int) -> dict[str, Any]:
    ok = await asyncio.to_thread(mark_processed_sync, visit_id)
    if not ok:
        raise HTTPException(status_code=404, detail="visit not found")
    return {"id": visit_id, "status": "processed"}


@router.post("/intake/start")
async def start_intake(request: Request) -> dict[str, Any]:
    """Кнопка «Оформить визит» на панели охраны: робот начинает опрос."""
    container: AppContainer = request.app.state.container
    await container.event_bus.publish(
        VisitIntakeStart(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.visits",
            ),
            actor="guard-panel",
        )
    )
    return {"started": True}
