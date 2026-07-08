"""RerankerPort using BGE-Reranker v2-m3."""

from __future__ import annotations

import asyncio
import importlib
import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict


class BgeRerankerRuntimeNotAvailableError(RuntimeError):
    """Raised when `FlagEmbedding` is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "FlagEmbedding is not installed. Install this adapter with its "
            "runtime extra: uv add 'humanoid-robot-adapters-rerank-bge[runtime]'"
        )


class BgeRerankerConfig(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cuda"
    use_fp16: bool = True


@dataclass(slots=True)
class BgeRerankerV2M3:
    """Cross-encoder reranker."""

    config: BgeRerankerConfig
    _loader: Any = None
    _model: Any = None

    def __init__(
        self,
        config: BgeRerankerConfig | None = None,
        *,
        loader: Any = None,
    ) -> None:
        self.config = config or BgeRerankerConfig()
        self._loader = loader
        self._model = None

    async def rerank(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        if not passages:
            return ()
        model = self._ensure_model()
        loop = asyncio.get_running_loop()
        raw_scores = await loop.run_in_executor(
            None,
            lambda: model.compute_score(
                [[query, p] for p in passages],
                normalize=False,
            ),
        )
        scores = raw_scores if isinstance(raw_scores, list) else [raw_scores]
        return tuple(_sigmoid(float(s)) for s in scores)

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._loader is not None:
            self._model = self._loader(self.config)
            return self._model
        try:
            fe = importlib.import_module("FlagEmbedding")
        except ImportError as exc:
            raise BgeRerankerRuntimeNotAvailableError from exc
        self._model = fe.FlagReranker(
            self.config.model_name,
            use_fp16=self.config.use_fp16,
            device=self.config.device,
        )
        return self._model


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def build_bge_reranker(**kwargs: object) -> BgeRerankerV2M3:
    """Entry-point factory."""
    return BgeRerankerV2M3(config=BgeRerankerConfig.model_validate(kwargs))
