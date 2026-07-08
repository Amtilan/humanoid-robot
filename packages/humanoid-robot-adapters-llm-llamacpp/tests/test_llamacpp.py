"""LlamaCppLlm tests against a mocked httpx transport."""

from __future__ import annotations

import json

import httpx
import pytest

from humanoid_robot.adapters.llm_llamacpp import LlamaCppConfig, LlamaCppLlm
from humanoid_robot.ports.ai import LlmRequest


def _mock_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="http://x")


class TestLlamaCppLlm:
    async def test_generate_returns_llm_response(self) -> None:
        received: list[dict[str, object]] = []

        def handle(request: httpx.Request) -> httpx.Response:
            received.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "choices": [{"text": "Привет робот", "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                },
            )

        transport = httpx.MockTransport(handle)
        llm = LlamaCppLlm(client=_mock_client(transport))
        try:
            result = await llm.generate(LlmRequest(system_prompt="be helpful", user_prompt="hi"))
        finally:
            await llm.close()

        assert result.text == "Привет робот"
        assert result.prompt_tokens == 12
        assert result.completion_tokens == 3
        assert result.finish_reason == "stop"
        # Prompt was composed from system + user.
        assert received[0]["prompt"] == "be helpful\n\nhi"
        assert received[0]["stream"] is False

    async def test_generate_uses_configured_model(self) -> None:
        captured: list[dict[str, object]] = []

        def handle(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "choices": [{"text": "", "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                },
            )

        llm = LlamaCppLlm(
            config=LlamaCppConfig(model="qwen3-4b-instruct"),
            client=_mock_client(httpx.MockTransport(handle)),
        )
        try:
            await llm.generate(LlmRequest(system_prompt="", user_prompt="?"))
        finally:
            await llm.close()
        assert captured[0]["model"] == "qwen3-4b-instruct"

    async def test_stream_yields_tokens(self) -> None:
        body = "\n".join(
            [
                'data: {"choices": [{"text": "Пр"}]}',
                'data: {"choices": [{"text": "и"}]}',
                'data: {"choices": [{"text": "вет"}]}',
                "data: [DONE]",
                "",
            ]
        )

        def handle(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body.encode("utf-8"),
            )

        llm = LlamaCppLlm(client=_mock_client(httpx.MockTransport(handle)))
        try:
            tokens = [
                t async for t in llm.stream(LlmRequest(system_prompt="", user_prompt="say hi"))
            ]
        finally:
            await llm.close()
        assert "".join(tokens) == "Привет"

    async def test_http_error_surfaces(self) -> None:
        def handle(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        llm = LlamaCppLlm(client=_mock_client(httpx.MockTransport(handle)))
        with pytest.raises(httpx.HTTPStatusError):
            await llm.generate(LlmRequest(system_prompt="", user_prompt="x"))
        await llm.close()
