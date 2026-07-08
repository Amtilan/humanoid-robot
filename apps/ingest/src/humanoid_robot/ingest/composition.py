"""Composition root for cortex-ingest."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, cast

from humanoid_robot.ingest.settings import (
    AdapterSelection,
    IngestSettings,
    ParserBinding,
)
from humanoid_robot.ports import (
    ChunkerPort,
    DocumentParserPort,
    EmbeddingPort,
    VectorStorePort,
)

_PARSER_GROUP = "humanoid_robot.parser_adapters"
_CHUNKER_GROUP = "humanoid_robot.chunker_adapters"
_EMBED_GROUP = "humanoid_robot.embedding_adapters"
_VECTOR_GROUP = "humanoid_robot.vector_adapters"


class UnknownAdapterError(LookupError):
    """The runtime asked for an adapter no installed distribution provides."""


@dataclass(slots=True)
class IngestComposition:
    """Composed ingest runtime — created once by the CLI."""

    settings: IngestSettings
    parsers: dict[str, DocumentParserPort]
    chunker: ChunkerPort
    embedder: EmbeddingPort
    vector_store: VectorStorePort

    @classmethod
    def build(cls, settings: IngestSettings) -> IngestComposition:
        stack = settings.stack
        chunker = _resolve(_CHUNKER_GROUP, stack.chunker)
        embedder = _resolve(_EMBED_GROUP, stack.embedder)
        vector_store = _resolve(_VECTOR_GROUP, stack.vector_store, embedder=embedder)
        parsers = {b.extension.lower(): _resolve(_PARSER_GROUP, b.adapter) for b in stack.parsers}
        _ = ParserBinding  # keep import alive
        return cls(
            settings=settings,
            parsers=cast(dict[str, DocumentParserPort], parsers),
            chunker=cast(ChunkerPort, chunker),
            embedder=cast(EmbeddingPort, embedder),
            vector_store=cast(VectorStorePort, vector_store),
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
