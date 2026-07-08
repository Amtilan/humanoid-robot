"""Composition root for cortex-rag.

Vector stores depend on the embedder (they need it to embed on upsert +
search). The composition root binds them explicitly here — it does not
leak into the entry-point contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, cast

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.ports import (
    EmbeddingPort,
    EventBusPort,
    LlmPort,
    RerankerPort,
    VectorStorePort,
)
from humanoid_robot.rag.settings import (
    AdapterSelection,
    NatsSettings,
    RagRunnerSettings,
)

_LLM_GROUP = "humanoid_robot.llm_adapters"
_EMBED_GROUP = "humanoid_robot.embedding_adapters"
_RERANK_GROUP = "humanoid_robot.reranker_adapters"
_VECTOR_GROUP = "humanoid_robot.vector_adapters"


class UnknownAdapterError(LookupError):
    """The runtime asked for an adapter no installed distribution provides."""


@dataclass(slots=True)
class RagComposition:
    """Composed RAG runtime — created once by the CLI."""

    settings: RagRunnerSettings
    embedder: EmbeddingPort
    reranker: RerankerPort
    llm: LlmPort
    vector_store: VectorStorePort
    bus: EventBusPort

    @classmethod
    async def build(cls, settings: RagRunnerSettings) -> RagComposition:
        stack = settings.stack
        embedder = _resolve(_EMBED_GROUP, stack.embedder)
        reranker = _resolve(_RERANK_GROUP, stack.reranker)
        llm = _resolve(_LLM_GROUP, stack.llm)
        vector_store = _resolve(_VECTOR_GROUP, stack.vector_store, embedder=embedder)
        bus = await _build_nats(settings.nats)
        return cls(
            settings=settings,
            embedder=cast(EmbeddingPort, embedder),
            reranker=cast(RerankerPort, reranker),
            llm=cast(LlmPort, llm),
            vector_store=cast(VectorStorePort, vector_store),
            bus=bus,
        )


def _resolve(group: str, selection: AdapterSelection, **extra: Any) -> Any:
    for ep in entry_points(group=group):
        if ep.name == selection.name:
            factory: Callable[..., Any] = ep.load()
            kwargs: dict[str, Any] = {**selection.config, **extra}
            return factory(**kwargs)
    available = sorted(ep.name for ep in entry_points(group=group))
    msg = (
        f"no adapter named {selection.name!r} in entry-point group {group!r}; "
        f"available: {available or '<none>'}"
    )
    raise UnknownAdapterError(msg)


async def _build_nats(cfg: NatsSettings) -> EventBusPort:
    bus = NatsEventBus(
        config=NatsEventBusConfig(
            servers=cfg.servers,
            name=cfg.client_name,
            connect_timeout_s=cfg.connect_timeout_s,
            reconnect_time_wait_s=cfg.reconnect_time_wait_s,
            max_reconnect_attempts=cfg.max_reconnect_attempts,
        )
    )
    await bus.connect()
    return bus
