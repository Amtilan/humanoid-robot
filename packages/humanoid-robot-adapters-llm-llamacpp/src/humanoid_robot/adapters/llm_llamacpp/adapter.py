"""LlmPort backed by a llama.cpp HTTP server.

We hit the OpenAI-compat `/completions` endpoint (not `/chat/completions`)
so the caller controls prompt formatting explicitly — this matches the
grounded-QA style where the RAG orchestrator constructs the system/user
prompt with retrieved context and expects a raw text completion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.ports.ai import LlmRequest, LlmResponse


class LlamaCppConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "http://127.0.0.1:8080"
    model: str = "qwen3-8b-instruct-q4_k_m"
    request_timeout_s: float = 60.0
    max_retries: int = Field(default=1, ge=0, le=5)


@dataclass(slots=True)
class LlamaCppLlm:
    """Wraps an already-running llama.cpp server."""

    config: LlamaCppConfig
    _client: httpx.AsyncClient | None = None

    def __init__(
        self,
        config: LlamaCppConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or LlamaCppConfig()
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.request_timeout_s,
            )
        return self._client

    async def generate(self, request: LlmRequest) -> LlmResponse:
        payload = self._build_payload(request, stream=False)
        response = await self._http().post("/v1/completions", json=payload)
        response.raise_for_status()
        body = response.json()
        text, prompt_tokens, completion_tokens, finish_reason = _parse_completion(body)
        return LlmResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )

    async def stream(self, request: LlmRequest) -> AsyncIterator[str]:
        payload = self._build_payload(request, stream=True)
        async with self._http().stream(
            "POST", "/v1/completions", json=payload, headers={"Accept": "text/event-stream"}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                token = _sse_token(line)
                if token is None:
                    continue
                if not token:
                    return
                yield token

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_payload(self, request: LlmRequest, *, stream: bool) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "prompt": _compose_prompt(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stop": list(request.stop) or None,
            "stream": stream,
            "grammar": request.grammar_gbnf,
        }


def _compose_prompt(request: LlmRequest) -> str:
    if request.system_prompt.strip():
        return f"{request.system_prompt}\n\n{request.user_prompt}"
    return request.user_prompt


def _parse_completion(body: dict[str, Any]) -> tuple[str, int, int, str]:
    choices = body.get("choices") or []
    text = choices[0].get("text", "") if choices else ""
    finish_reason = choices[0].get("finish_reason", "stop") if choices else "stop"
    usage = body.get("usage") or {}
    return (
        text,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
        str(finish_reason),
    )


def _sse_token(line: str) -> str | None:
    """Return the incremental text token from an SSE line, or None to skip."""
    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return ""
    import json

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    choices = payload.get("choices") or []
    if not choices:
        return None
    return str(choices[0].get("text", ""))


def build_llama_cpp_llm(**kwargs: object) -> LlamaCppLlm:
    """Entry-point factory — accepts flat kwargs from the CLI."""
    return LlamaCppLlm(config=LlamaCppConfig.model_validate(kwargs))
