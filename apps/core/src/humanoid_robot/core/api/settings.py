"""Read-only settings endpoint.

Exposes the current `CoreSettings` in a form safe to render in the browser.
Any TLS credentials paths are truncated to their filename so operators can
verify configuration without leaking the full path.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from humanoid_robot.core.container import AppContainer

router = APIRouter()


class SettingsResponse(BaseModel):
    settings: dict[str, Any]


_SECRET_KEYS = {"user_credentials", "tls_ca", "tls_cert", "tls_key"}


@router.get("/", response_model=SettingsResponse)
async def read_settings(request: Request) -> SettingsResponse:
    container: AppContainer = request.app.state.container
    raw = container.settings.model_dump(mode="json")
    return SettingsResponse(settings=_redact(raw))


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            result[key] = _redact(value)
        elif key in _SECRET_KEYS and isinstance(value, str) and value:
            result[key] = f"<redacted: {PurePath(value).name}>"
        else:
            result[key] = value
    return result
