"""LlmPort backed by a llama.cpp HTTP server.

Two endpoints, picked by whether the request carries a grammar:

* Grounded QA constrains output with a GBNF grammar → the raw `/v1/completions`
  endpoint, where the orchestrator controls prompt formatting explicitly.
* Free-form conversation (no grammar) → `/v1/chat/completions`, so llama.cpp
  applies the model's own chat template (e.g. Qwen's <|im_start|> turns). An
  instruct model driven through raw completions just continues the text and
  rambles; the chat endpoint yields proper single-turn replies.
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
        chat = request.grammar_gbnf is None
        endpoint = "/v1/chat/completions" if chat else "/v1/completions"
        payload = self._build_payload(request, stream=False)
        response = await self._http().post(endpoint, json=payload)
        response.raise_for_status()
        body = response.json()
        text, prompt_tokens, completion_tokens, finish_reason = _parse_completion(body, chat=chat)
        return LlmResponse(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )

    async def stream(self, request: LlmRequest) -> AsyncIterator[str]:
        chat = request.grammar_gbnf is None
        endpoint = "/v1/chat/completions" if chat else "/v1/completions"
        payload = self._build_payload(request, stream=True)
        async with self._http().stream(
            "POST", endpoint, json=payload, headers={"Accept": "text/event-stream"}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                token = _sse_token(line, chat=chat)
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
        common: dict[str, Any] = {
            "model": self.config.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stop": list(request.stop) or None,
            "stream": stream,
        }
        if request.grammar_gbnf is None:
            # Chat endpoint: llama.cpp applies the model's chat template.
            messages: list[dict[str, str]] = []
            if request.system_prompt.strip():
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.user_prompt})
            return {**common, "messages": messages}
        return {**common, "prompt": _compose_prompt(request), "grammar": request.grammar_gbnf}


def _compose_prompt(request: LlmRequest) -> str:
    if request.system_prompt.strip():
        return f"{request.system_prompt}\n\n{request.user_prompt}"
    return request.user_prompt


def _parse_completion(body: dict[str, Any], *, chat: bool) -> tuple[str, int, int, str]:
    choices = body.get("choices") or []
    first = choices[0] if choices else {}
    text = (first.get("message", {}).get("content", "") if chat else first.get("text", "")) or ""
    finish_reason = first.get("finish_reason", "stop") if choices else "stop"
    usage = body.get("usage") or {}
    return (
        text,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
        str(finish_reason),
    )


def _sse_token(line: str, *, chat: bool) -> str | None:
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
    if chat:
        return str(choices[0].get("delta", {}).get("content", ""))
    return str(choices[0].get("text", ""))


def build_llama_cpp_llm(**kwargs: object) -> LlamaCppLlm:
    """Entry-point factory — accepts flat kwargs from the CLI."""
    return LlamaCppLlm(config=LlamaCppConfig.model_validate(kwargs))
