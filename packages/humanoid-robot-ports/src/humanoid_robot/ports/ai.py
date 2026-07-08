"""AI ports — ASR, LLM, TTS, embeddings.

These are transport-agnostic contracts. NATS-based workers implement them
under the hood; from the domain's viewpoint, all it sees is `await asr.transcribe(...)`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.voice import Language, Transcription
from humanoid_robot.ports.robot import AudioFrame


class AsrStreamChunk(BaseModel):
    """A single incremental update from a streaming ASR session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    is_final: bool
    stable_prefix_len: int = Field(ge=0)


@runtime_checkable
class AsrPort(Protocol):
    """Streaming ASR."""

    def transcribe_stream(
        self,
        frames: AsyncIterator[AudioFrame],
        *,
        language_hint: Language | None = None,
    ) -> AsyncIterator[AsrStreamChunk]: ...

    async def transcribe_batch(
        self,
        pcm: bytes,
        *,
        sample_rate_hz: int,
        language_hint: Language | None = None,
    ) -> Transcription: ...


class LlmRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system_prompt: str
    user_prompt: str
    grammar_gbnf: str | None = None
    temperature: float = Field(ge=0.0, le=2.0, default=0.2)
    max_tokens: int = Field(gt=0, le=8192, default=1024)
    stop: tuple[str, ...] = ()


class LlmResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str


@runtime_checkable
class LlmPort(Protocol):
    """Grounded LLM inference with optional streaming."""

    async def generate(self, request: LlmRequest) -> LlmResponse: ...

    def stream(self, request: LlmRequest) -> AsyncIterator[str]: ...


class TtsRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    language: Language
    voice_id: str | None = None
    speed: float = Field(gt=0.0, le=2.0, default=1.0)


@runtime_checkable
class TtsPort(Protocol):
    """Text-to-speech, streaming and one-shot."""

    def synthesize_stream(self, request: TtsRequest) -> AsyncIterator[AudioFrame]: ...

    async def synthesize(self, request: TtsRequest) -> AudioFrame: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Produces dense and sparse embeddings for retrieval."""

    async def embed_dense(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...

    async def embed_sparse(self, texts: tuple[str, ...]) -> tuple[dict[int, float], ...]: ...

    @property
    def dimension(self) -> int: ...


@runtime_checkable
class RerankerPort(Protocol):
    """Cross-encoder reranker — returns a per-passage relevance score in [0, 1]."""

    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]: ...
