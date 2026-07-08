"""EmbeddingPort via `BGEM3FlagModel`.

Design:
    - Lazy import of `FlagEmbedding` — the package installs cleanly without
      torch/transformers.
    - The model is loaded once on first call. The blocking encode runs in a
      worker thread so async callers remain responsive.
    - `dimension` reflects BGE-M3's 1024 dense dimension.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

_DENSE_DIM = 1024


class BgeM3RuntimeNotAvailableError(RuntimeError):
    """Raised when `FlagEmbedding` is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "FlagEmbedding is not installed. Install this adapter with its "
            "runtime extra: uv add 'humanoid-robot-adapters-embed-bge[runtime]'"
        )


class BgeM3Config(BaseModel):
    """Runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = "BAAI/bge-m3"
    device: str = "cuda"
    use_fp16: bool = True
    max_length: int = 8192


@dataclass(slots=True)
class BgeM3Embedder:
    """BGE-M3 dense + sparse embedder."""

    config: BgeM3Config
    _loader: Any = None  # optional test double
    _model: Any = None

    def __init__(
        self,
        config: BgeM3Config | None = None,
        *,
        loader: Any = None,
    ) -> None:
        self.config = config or BgeM3Config()
        self._loader = loader
        self._model = None

    @property
    def dimension(self) -> int:
        return _DENSE_DIM

    async def embed_dense(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        result = await self._encode(list(texts), sparse=False)
        dense = result["dense_vecs"]
        return tuple(tuple(float(x) for x in row) for row in dense)

    async def embed_sparse(self, texts: tuple[str, ...]) -> tuple[dict[int, float], ...]:
        result = await self._encode(list(texts), sparse=True)
        sparse = result["lexical_weights"]
        return tuple({int(k): float(v) for k, v in row.items()} for row in sparse)

    async def _encode(self, texts: list[str], *, sparse: bool) -> dict[str, Any]:
        model = self._ensure_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: model.encode(
                texts,
                return_dense=True,
                return_sparse=sparse,
                return_colbert_vecs=False,
                max_length=self.config.max_length,
            ),
        )

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._loader is not None:
            self._model = self._loader(self.config)
            return self._model
        try:
            fe = importlib.import_module("FlagEmbedding")
        except ImportError as exc:
            raise BgeM3RuntimeNotAvailableError from exc
        self._model = fe.BGEM3FlagModel(
            self.config.model_name,
            use_fp16=self.config.use_fp16,
            device=self.config.device,
        )
        return self._model


def build_bge_m3(**kwargs: object) -> BgeM3Embedder:
    """Entry-point factory."""
    return BgeM3Embedder(config=BgeM3Config.model_validate(kwargs))
