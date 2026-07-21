"""LLM backend switching — local llama.cpp ⇄ cloud (OpenAI-compatible).

The operator sets this FROM THE APP (Ещё → Модель ИИ): the api key never
lives in an image or a config file in git — core persists it on the
core-state volume and announces the change on the bus (without the secret);
cortex-rag then fetches the full config over HTTP and reconfigures its LLM
client live, no restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from humanoid_robot.core.container import AppContainer
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import LlmConfigChanged
from humanoid_robot.events.base import EventMetadata

router = APIRouter()

_CONFIG_PATH = Path("/var/lib/humanoid-robot/llm-config.json")
_DEFAULT_CLOUD_BASE_URL = "https://api.openai.com"


class LlmConfig(BaseModel):
    """Stored LLM backend selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["local", "cloud"] = "local"
    # Cloud fields (ignored in local mode).
    base_url: str = _DEFAULT_CLOUD_BASE_URL
    model: str = "gpt-4o-mini"
    api_key: str = ""


def load_llm_config() -> LlmConfig:
    try:
        return LlmConfig.model_validate(json.loads(_CONFIG_PATH.read_text()))
    except Exception:
        return LlmConfig()


@router.get("/config", response_model=LlmConfig)
async def get_config() -> LlmConfig:
    """Full stored config. The dashboard masks the key client-side; rag needs
    the real value to talk to the provider."""
    return load_llm_config()


@router.post("/config", response_model=LlmConfig)
async def set_config(body: LlmConfig, request: Request) -> LlmConfig:
    if body.mode == "cloud":
        if not body.api_key.strip():
            raise HTTPException(status_code=422, detail="cloud mode requires api_key")
        if not body.model.strip():
            raise HTTPException(status_code=422, detail="cloud mode requires model")
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(body.model_dump_json())
    _CONFIG_PATH.chmod(0o600)
    container: AppContainer = request.app.state.container
    await container.event_bus.publish(
        LlmConfigChanged(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="cortex-core.llm_config",
            ),
            mode=body.mode,
            model=body.model if body.mode == "cloud" else "",
        )
    )
    return body
