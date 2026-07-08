"""BGE-M3 embeddings adapter."""

from humanoid_robot.adapters.embed_bge.adapter import (
    BgeM3Config,
    BgeM3Embedder,
    BgeM3RuntimeNotAvailableError,
    build_bge_m3,
)

__all__ = [
    "BgeM3Config",
    "BgeM3Embedder",
    "BgeM3RuntimeNotAvailableError",
    "build_bge_m3",
]
