# humanoid-robot-adapters-embed-bge

`EmbeddingPort` on top of BGE-M3 (`BAAI/bge-m3`, MIT), the multilingual model
selected in ADR-0005.  BGE-M3 emits dense + sparse (BM25-like) + colbert
multi-vector embeddings in one forward pass; the port surfaces the dense
and sparse halves that our Qdrant hybrid retrieval consumes.

## Installation

```bash
uv add "humanoid-robot-adapters-embed-bge[runtime]"
```

`FlagEmbedding` pulls torch — this is the largest single runtime dependency
in the platform (~800 MB with CUDA wheels). Only install it on the target
robot, not on developer laptops. The adapter package itself imports fine
without any of the runtime deps.
