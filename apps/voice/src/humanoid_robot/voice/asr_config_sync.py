"""Keep cloud transcription in sync with the app's AI backend choice.

Same contract as rag's LlmConfigSync: core persists the operator's choice
and publishes ``llm.config.changed`` WITHOUT the secret; we fetch the full
config over HTTP. Cloud mode + token ⇒ transcription goes through the
provider's audio API too (with local fallback); local mode ⇒ local whisper.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from humanoid_robot.events import BaseEvent, LlmConfigChanged
from humanoid_robot.observability import get_logger
from humanoid_robot.ports import EventBusPort, Subscription
from humanoid_robot.voice.cloud_asr import SwitchableAsr

_LOG = get_logger("cortex-voice.asr_config")

# The voice container runs on host network on the robot, so core is reachable
# on loopback there; the compose overlay sets this env accordingly.
_CORE_URL = os.environ.get("HR_VOICE_CORE_URL", "http://core:8080")

_STARTUP_RETRIES = 10
_STARTUP_RETRY_DELAY_S = 3.0


class AsrConfigSync:
    """Applies the stored AI backend choice to the SwitchableAsr."""

    def __init__(self, asr: SwitchableAsr) -> None:
        self._asr = asr
        self._startup_task: asyncio.Task[None] | None = None

    async def start(self, bus: EventBusPort) -> Subscription:
        if not await self.apply():
            self._startup_task = asyncio.create_task(
                self._retry_initial_apply(), name="asr-config-initial-apply"
            )
        return await bus.subscribe(LlmConfigChanged.subject, self._on_changed)

    async def _retry_initial_apply(self) -> None:
        for _ in range(_STARTUP_RETRIES):
            await asyncio.sleep(_STARTUP_RETRY_DELAY_S)
            if await self.apply():
                return
        _LOG.warning("asr_config.startup_fetch_gave_up", core_url=_CORE_URL)

    async def _on_changed(self, event: BaseEvent) -> None:
        if isinstance(event, LlmConfigChanged):
            await self.apply()

    async def apply(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{_CORE_URL}/api/v1/llm/config")
                response.raise_for_status()
                config = response.json()
        except Exception:
            _LOG.warning("asr_config.fetch_failed", core_url=_CORE_URL)
            return False
        if config.get("mode") == "cloud" and config.get("api_key"):
            self._asr.reconfigure_cloud(
                base_url=str(config.get("base_url") or "https://api.openai.com"),
                api_key=str(config["api_key"]),
            )
        else:
            self._asr.reset_local()
        return True
