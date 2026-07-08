"""Token-aware chunker with paragraph-preserving boundaries."""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from humanoid_robot.domain.knowledge import KnowledgeChunk, KnowledgeSource

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


class TokenChunkerConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_tokens: int = Field(default=512, ge=32, le=4096)
    hard_max_tokens: int = Field(default=768, ge=64, le=8192)
    overlap_tokens: int = Field(default=64, ge=0, le=512)
    chars_per_token: float = Field(default=4.0, gt=0.5, le=10.0)


@dataclass(slots=True)
class TokenChunker:
    """Character-based estimate of tokens; paragraph-first splitter."""

    config: TokenChunkerConfig = field(default_factory=TokenChunkerConfig)

    def chunk(self, source: KnowledgeSource, text: str) -> AsyncIterator[KnowledgeChunk]:
        async def _gen() -> AsyncIterator[KnowledgeChunk]:
            target_chars = int(self.config.target_tokens * self.config.chars_per_token)
            hard_max_chars = int(self.config.hard_max_tokens * self.config.chars_per_token)
            overlap_chars = int(self.config.overlap_tokens * self.config.chars_per_token)

            segments = _split_into_paragraphs(text)
            buffer = ""
            ordinal = 0

            def _flush() -> tuple[str, str]:
                # Emit current buffer, then compute overlap-prefix for the next.
                if not buffer.strip():
                    return "", ""
                overlap = buffer[-overlap_chars:] if overlap_chars else ""
                return buffer, overlap

            for segment in segments:
                candidate = f"{buffer}\n\n{segment}" if buffer else segment
                if _len(candidate) <= target_chars:
                    buffer = candidate
                    continue
                # Segment does not fit: flush current buffer, then split segment.
                if buffer:
                    payload, overlap = _flush()
                    if payload.strip():
                        yield _mk_chunk(source, ordinal, payload, self.config)
                        ordinal += 1
                    buffer = overlap
                for piece in _split_oversize(segment, hard_max_chars, target_chars):
                    candidate2 = f"{buffer}{piece}" if buffer else piece
                    if _len(candidate2) <= target_chars:
                        buffer = candidate2
                        continue
                    if buffer:
                        payload, overlap = _flush()
                        if payload.strip():
                            yield _mk_chunk(source, ordinal, payload, self.config)
                            ordinal += 1
                        buffer = overlap + piece
                    else:
                        buffer = piece

            if buffer.strip():
                yield _mk_chunk(source, ordinal, buffer, self.config)

        return _gen()


def _len(s: str) -> int:
    return len(s)


def _split_into_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    return parts or [text.strip()]


def _split_oversize(segment: str, hard_max_chars: int, target_chars: int) -> list[str]:
    """Split a paragraph too big to fit into sentence-ish pieces."""
    del target_chars  # kept for future reuse; currently only hard_max matters
    if len(segment) <= hard_max_chars:
        return [segment]
    sentences = _SENTENCE_SPLIT_RE.split(segment)
    pieces: list[str] = []
    for sent in sentences:
        stripped = sent.strip()
        if not stripped:
            continue
        if len(stripped) <= hard_max_chars:
            pieces.append(stripped)
            continue
        # Sentence itself exceeds hard max — hard-slice.
        pieces.extend(_hard_slice(stripped, hard_max_chars))
    return pieces or _hard_slice(segment, hard_max_chars)


def _hard_slice(s: str, hard_max_chars: int) -> list[str]:
    return [s[i : i + hard_max_chars] for i in range(0, len(s), hard_max_chars)]


def _mk_chunk(
    source: KnowledgeSource,
    ordinal: int,
    text: str,
    config: TokenChunkerConfig,
) -> KnowledgeChunk:
    content = text.strip()
    token_estimate = int(len(content) / config.chars_per_token)
    chunk_id = _chunk_id(source.id, ordinal, content)
    return KnowledgeChunk(
        id=chunk_id,
        source_id=source.id,
        ordinal=ordinal,
        content=content,
        token_count=token_estimate,
    )


def _chunk_id(source_id: str, ordinal: int, content: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{ordinal}:{content}".encode()).hexdigest()
    return f"chk_{digest[:32]}"


def build_token_chunker(**kwargs: object) -> TokenChunker:
    return TokenChunker(config=TokenChunkerConfig.model_validate(kwargs))
