"""TokenChunker tests."""

from __future__ import annotations

from humanoid_robot.adapters.chunker_token import TokenChunker, TokenChunkerConfig
from humanoid_robot.domain.knowledge import KnowledgeSource, KnowledgeSourceKind


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        id="src1",
        uri="file:///tmp/x.txt",
        kind=KnowledgeSourceKind.TEXT,
        title="x",
        content_hash="abc",
    )


class TestTokenChunker:
    async def test_short_text_becomes_one_chunk(self) -> None:
        chunker = TokenChunker(TokenChunkerConfig(target_tokens=128))
        chunks = [c async for c in chunker.chunk(_source(), "Hello world.")]
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world."
        assert chunks[0].ordinal == 0

    async def test_paragraphs_are_split_at_blank_lines(self) -> None:
        # target_tokens=32 → ~128 chars per chunk. Two ~200-char paragraphs
        # cannot both fit → should produce 2 chunks.
        p1 = "A" * 200
        p2 = "B" * 200
        text = f"{p1}\n\n{p2}"
        chunker = TokenChunker(
            TokenChunkerConfig(target_tokens=32, hard_max_tokens=64, overlap_tokens=0)
        )
        chunks = [c async for c in chunker.chunk(_source(), text)]
        assert len(chunks) >= 2

    async def test_hard_max_respected(self) -> None:
        # A single paragraph much larger than hard_max should be sliced.
        text = "X" * 5000
        chunker = TokenChunker(
            TokenChunkerConfig(
                target_tokens=32,
                hard_max_tokens=64,
                overlap_tokens=0,
                chars_per_token=4.0,
            )
        )
        chunks = [c async for c in chunker.chunk(_source(), text)]
        # hard_max_chars = 64 * 4 = 256 → 5000 / 256 ≈ 20 chunks.
        assert len(chunks) >= 15
        for c in chunks:
            assert len(c.content) <= 256

    async def test_overlap_glues_boundaries(self) -> None:
        # Two paragraphs whose combined length fits in the hard_max but not
        # in the target — forces a split between them with overlap carryover.
        p1 = "A" * 400
        p2 = "B" * 200
        text = f"{p1}\n\n{p2}"
        chunker = TokenChunker(
            TokenChunkerConfig(
                target_tokens=80,  # ~320 chars target
                hard_max_tokens=200,  # ~800 chars hard max
                overlap_tokens=16,
                chars_per_token=4.0,
            )
        )
        chunks = [c async for c in chunker.chunk(_source(), text)]
        assert len(chunks) >= 2
        assert chunks[1].content

    async def test_chunk_ids_are_deterministic(self) -> None:
        text = "one\n\ntwo\n\nthree\n\nfour" * 40  # enough to force multiple chunks
        chunker = TokenChunker(TokenChunkerConfig(target_tokens=32, chars_per_token=1.0))
        first = [c async for c in chunker.chunk(_source(), text)]
        second = [c async for c in chunker.chunk(_source(), text)]
        assert [c.id for c in first] == [c.id for c in second]

    async def test_token_count_is_estimated(self) -> None:
        chunker = TokenChunker(TokenChunkerConfig(chars_per_token=4.0))
        (chunk,) = [c async for c in chunker.chunk(_source(), "12345678")]
        assert chunk.token_count == 2
