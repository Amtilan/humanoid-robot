"""Live LLM backend switching for cortex-rag.

The operator picks local ⇄ cloud in the app; core persists the choice (with
the api key) and publishes ``llm.config.changed`` WITHOUT the secret. This
module fetches the full config from core over HTTP and reconfigures the
running LLM adapter in place — no restarts, no keys in images or git.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from humanoid_robot.events import BaseEvent, LlmConfigChanged
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription

_LOG = get_logger("cortex-rag.llm_config")

_CORE_URL = os.environ.get("HR_RAG_CORE_URL", "http://core:8080")

# After a robot reboot rag often comes up before core is ready; without a
# retry a stored cloud choice would silently fall back to the local model.
_STARTUP_RETRIES = 10
_STARTUP_RETRY_DELAY_S = 3.0


class LlmConfigSync:
    """Keeps the LLM adapter's backend in sync with core's stored choice."""

    def __init__(self, llm: Any, *, local_base_url: str, local_model: str) -> None:
        # Duck-typed: the adapter exposes `reconfigure(base_url, model, api_key)`.
        self._llm = llm
        self._local_base_url = local_base_url
        self._local_model = local_model
        self._startup_task: asyncio.Task[None] | None = None

    async def start(self, bus: EventBusPort) -> Subscription:
        # Pick up a stored cloud choice across restarts. Retried in the
        # background so a not-yet-ready core doesn't block rag startup.
        if not await self.apply():
            self._startup_task = asyncio.create_task(
                self._retry_initial_apply(), name="llm-config-initial-apply"
            )
        return await bus.subscribe(LlmConfigChanged.subject, self._on_changed)

    async def _retry_initial_apply(self) -> None:
        for _ in range(_STARTUP_RETRIES):
            await asyncio.sleep(_STARTUP_RETRY_DELAY_S)
            if await self.apply():
                return
        _LOG.warning("llm_config.startup_fetch_gave_up", core_url=_CORE_URL)

    async def _on_changed(self, event: BaseEvent) -> None:
        if isinstance(event, LlmConfigChanged):
            await self.apply()

    async def apply(self) -> bool:
        reconfigure = getattr(self._llm, "reconfigure", None)
        if reconfigure is None:
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{_CORE_URL}/api/v1/llm/config")
                response.raise_for_status()
                config = response.json()
        except Exception:
            _LOG.warning("llm_config.fetch_failed", core_url=_CORE_URL)
            return False
        if config.get("mode") == "cloud" and config.get("api_key"):
            await reconfigure(
                base_url=str(config.get("base_url") or "https://api.openai.com"),
                model=str(config.get("model") or "gpt-4o-mini"),
                api_key=str(config["api_key"]),
            )
            _LOG.info("llm_config.applied", mode="cloud", model=config.get("model"))
        else:
            await reconfigure(
                base_url=self._local_base_url,
                model=self._local_model,
                api_key="",
            )
            _LOG.info("llm_config.applied", mode="local", model=self._local_model)
        return True
