"""WallControlPort over HTTP — client for the ``cortex-wall-agent`` service."""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from humanoid_robot.domain.wall import (
    WallCommand,
    WallCommandOutcome,
    WallCommandResult,
)

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 5.0


class WallHttpClient:
    """Sends wall commands to the agent; maps transport failures to outcomes."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.AsyncClient(timeout=timeout_s)

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"X-Wall-Token": self._token}
        return {}

    async def send(self, command: WallCommand) -> WallCommandResult:
        try:
            response = await self._client.post(
                f"{self._base_url}/wall/command",
                json=command.model_dump(mode="json"),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            log.warning("wall agent unreachable: %s", exc)
            return WallCommandResult(
                outcome=WallCommandOutcome.UNREACHABLE,
                detail=f"{type(exc).__name__}: {exc}",
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            return WallCommandResult(
                outcome=WallCommandOutcome.REJECTED,
                detail=f"HTTP {response.status_code}: {response.text[:200]}",
            )
        try:
            return WallCommandResult.model_validate(response.json())
        except (ValueError, ValidationError):
            return WallCommandResult(outcome=WallCommandOutcome.ACCEPTED)

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._base_url}/healthz", headers=self._headers()
            )
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK

    async def close(self) -> None:
        await self._client.aclose()
