"""HITL smoke test for cortex-rag on a live robot.

Runs on the target host. Expects:

  - `nats-server` reachable at `HR_RAG_NATS`.
  - `llama-server` reachable at `HR_RAG_LLM_URL`, serving the model
    named `HR_RAG_LLM_MODEL`.
  - `humanoid-robot-adapters-embed-bge[runtime]`,
    `humanoid-robot-adapters-rerank-bge[runtime]`,
    `humanoid-robot-adapters-vector-qdrant[runtime]` installed.
  - A pre-populated Qdrant collection at `HR_RAG_QDRANT_PATH`.

Publishes a canned `asr.final` event; asserts `llm.answer` or
`llm.rejected` fires within 60 s.
"""

from __future__ import annotations

import asyncio
import os
import sys

from humanoid_robot.adapters.embed_bge import BgeM3Config, BgeM3Embedder
from humanoid_robot.adapters.llm_llamacpp import LlamaCppConfig, LlamaCppLlm
from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.adapters.rerank_bge import BgeRerankerConfig, BgeRerankerV2M3
from humanoid_robot.adapters.vector_qdrant import QdrantConfig, QdrantLocalStore
from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
    new_utterance_id,
)
from humanoid_robot.domain.voice import Language
from humanoid_robot.events import AsrFinal, BaseEvent, LlmAnswer, LlmRejected
from humanoid_robot.events.base import EventMetadata
from humanoid_robot.rag import (
    GroundedQAConfig,
    GroundedQAOrchestrator,
    RagRunner,
)


async def _main() -> int:
    nats_url = os.environ.get("HR_RAG_NATS", "nats://127.0.0.1:4222")
    llm_url = os.environ.get("HR_RAG_LLM_URL", "http://127.0.0.1:8080")
    llm_model = os.environ.get("HR_RAG_LLM_MODEL", "qwen3-8b-instruct-q4_k_m")
    qdrant_path = os.environ.get("HR_RAG_QDRANT_PATH", "/var/lib/humanoid-robot/qdrant")
    question = os.environ.get("HR_RAG_QUESTION", "Работает ли робот полностью офлайн?")

    bus = NatsEventBus(config=NatsEventBusConfig(servers=(nats_url,), name="hitl-rag"))
    await bus.connect()

    embedder = BgeM3Embedder(BgeM3Config())
    reranker = BgeRerankerV2M3(BgeRerankerConfig())
    llm = LlamaCppLlm(LlamaCppConfig(base_url=llm_url, model=llm_model))
    store = QdrantLocalStore(
        config=QdrantConfig(local_path=qdrant_path),
        embedder=embedder,
    )
    orch = GroundedQAOrchestrator(
        vector_store=store, reranker=reranker, llm=llm, config=GroundedQAConfig()
    )
    runner = RagRunner(orchestrator=orch, bus=bus)

    answered = asyncio.Event()

    async def _watch(ev: BaseEvent) -> None:
        if isinstance(ev, (LlmAnswer, LlmRejected)):
            answered.set()

    await bus.subscribe("llm.answer", _watch)
    await bus.subscribe("llm.rejected", _watch)

    run_task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.5)

    session_id = new_session_id()
    await bus.publish(
        AsrFinal(
            meta=EventMetadata(
                correlation_id=new_correlation_id(),
                producer="hitl-rag",
            ),
            session_id=session_id,
            utterance_id=new_utterance_id(),
            text=question,
            language=Language.RU,
            confidence=1.0,
        )
    )

    try:
        await asyncio.wait_for(answered.wait(), timeout=60.0)
        print("hitl rag smoke: OK")
        return 0
    except TimeoutError:
        print("hitl rag smoke: TIMEOUT waiting for llm.answer/llm.rejected", file=sys.stderr)
        return 1
    finally:
        runner.request_stop()
        await run_task
        await bus.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
