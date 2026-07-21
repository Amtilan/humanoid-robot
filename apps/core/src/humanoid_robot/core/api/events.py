"""Event bridge endpoints — WebSocket that pipes bus events to browsers."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from humanoid_robot.core.api.auth import enforce_ws_token
from humanoid_robot.core.container import AppContainer
from humanoid_robot.core.event_journal import list_events_sync
from humanoid_robot.events import BaseEvent
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort

_LOG = get_logger("cortex-core.api.events")

router = APIRouter()


@router.get("/history")
async def events_history(
    limit: int = Query(default=500, ge=1, le=2000),
    subject: str = Query(default="", description="Subject prefix filter."),
) -> dict[str, Any]:
    """Replay the persisted event tail (oldest-first) so a freshly opened
    page can seed itself before live WebSocket events arrive."""
    records = await asyncio.to_thread(list_events_sync, limit, subject)
    return {"records": records}


@router.websocket("/ws")
async def events_ws(
    websocket: WebSocket,
    subject: str = Query(default=">", description="NATS subject pattern to tail."),
) -> None:
    """WebSocket bridge that forwards bus events to a browser client.

    The client cannot publish through this endpoint — it is read-only.
    Every message sent to the browser is a single JSON object with
    ``subject``, ``event_id``, ``occurred_at``, and ``data`` fields.
    """
    container: AppContainer = websocket.app.state.container
    expected = container.settings.auth.token
    if not enforce_ws_token(
        expected,
        header=websocket.headers.get("authorization"),
        query_token=websocket.query_params.get("token"),
    ):
        # 4401 keeps it distinguishable from routing errors on the JS side.
        await websocket.close(code=4401)
        return
    await websocket.accept()
    bus: EventBusPort = container.event_bus

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

    async def _forward(event: BaseEvent) -> None:
        payload: dict[str, Any] = {
            "subject": type(event).subject,
            "event_id": event.meta.event_id,
            "occurred_at": event.meta.occurred_at.isoformat(),
            "correlation_id": event.meta.correlation_id,
            "producer": event.meta.producer,
            "data": event.model_dump(mode="json", exclude={"meta"}),
        }
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop under back-pressure rather than block the bus.
            _LOG.warning("events_ws.dropped", subject=type(event).subject)

    subscription = await bus.subscribe(subject, _forward)

    async def _pump() -> None:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump_task
        with contextlib.suppress(Exception):
            await subscription.cancel()
