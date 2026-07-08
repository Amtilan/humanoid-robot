"""BgeM3Embedder tests with an injected fake FlagEmbedding model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from humanoid_robot.adapters.embed_bge import (
    BgeM3Config,
    BgeM3Embedder,
    BgeM3RuntimeNotAvailableError,
)


@dataclass(slots=True)
class _FakeModel:
    dense_scale: float = 0.1
    encode_calls: list[dict[str, Any]] = field(default_factory=list)

    def encode(
        self,
        texts: list[str],
        *,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
        max_length: int,
    ) -> dict[str, Any]:
        self.encode_calls.append(
            {
                "n": len(texts),
                "return_dense": return_dense,
                "return_sparse": return_sparse,
                "return_colbert_vecs": return_colbert_vecs,
                "max_length": max_length,
            }
        )
        result: dict[str, Any] = {}
        if return_dense:
            result["dense_vecs"] = [
                [self.dense_scale * i for _ in range(1024)] for i in range(1, len(texts) + 1)
            ]
        if return_sparse:
            result["lexical_weights"] = [{i: 1.0 * (i + 1)} for i, _ in enumerate(texts)]
        return result


def _loader() -> Any:
    fake = _FakeModel()

    def _mk(_: BgeM3Config) -> _FakeModel:
        return fake

    _mk.fake = fake  # type: ignore[attr-defined]
    return _mk


class TestBgeM3Embedder:
    async def test_missing_runtime_raises(self) -> None:
        emb = BgeM3Embedder()
        with pytest.raises(BgeM3RuntimeNotAvailableError):
            await emb.embed_dense(("hi",))

    async def test_dense_returns_1024_dim_vectors(self) -> None:
        loader = _loader()
        emb = BgeM3Embedder(loader=loader)
        result = await emb.embed_dense(("hi", "there"))
        assert len(result) == 2
        assert all(len(vec) == 1024 for vec in result)

    async def test_sparse_returns_dict_per_text(self) -> None:
        loader = _loader()
        emb = BgeM3Embedder(loader=loader)
        result = await emb.embed_sparse(("a", "b"))
        assert len(result) == 2
        assert result[0] == {0: 1.0}
        assert result[1] == {1: 2.0}

    async def test_encode_uses_configured_max_length(self) -> None:
        loader = _loader()
        emb = BgeM3Embedder(config=BgeM3Config(max_length=256), loader=loader)
        await emb.embed_dense(("x",))
        assert loader.fake.encode_calls[0]["max_length"] == 256

    def test_dimension_is_1024(self) -> None:
        assert BgeM3Embedder().dimension == 1024
