"""BgeRerankerV2M3 tests with an injected fake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from humanoid_robot.adapters.rerank_bge import (
    BgeRerankerRuntimeNotAvailableError,
    BgeRerankerV2M3,
)


@dataclass(slots=True)
class _FakeModel:
    scripted: list[float]

    def compute_score(self, pairs: list[list[str]], *, normalize: bool) -> list[float]:
        del pairs, normalize
        return list(self.scripted)


def _loader(scripted: list[float]) -> Any:
    def _mk(_: Any) -> _FakeModel:
        return _FakeModel(scripted=scripted)

    return _mk


class TestBgeReranker:
    async def test_missing_runtime_raises(self) -> None:
        rr = BgeRerankerV2M3()
        with pytest.raises(BgeRerankerRuntimeNotAvailableError):
            await rr.rerank("q", ("a",))

    async def test_scores_are_normalized_via_sigmoid(self) -> None:
        rr = BgeRerankerV2M3(loader=_loader([0.0, 10.0, -10.0]))
        scores = await rr.rerank("q", ("a", "b", "c"))
        assert scores[0] == pytest.approx(0.5, abs=1e-6)
        assert scores[1] == pytest.approx(1.0, abs=1e-3)
        assert scores[2] == pytest.approx(0.0, abs=1e-3)

    async def test_empty_passages_returns_empty(self) -> None:
        rr = BgeRerankerV2M3(loader=_loader([]))
        scores = await rr.rerank("q", ())
        assert scores == ()

    async def test_single_score_normalized_correctly(self) -> None:
        rr = BgeRerankerV2M3(loader=_loader([5.0]))
        (score,) = await rr.rerank("q", ("a",))
        assert 0.99 < score < 1.0
