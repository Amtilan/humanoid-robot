# humanoid-robot-adapters-rerank-bge

`RerankerPort` on top of `BAAI/bge-reranker-v2-m3` (MIT), the multilingual
cross-encoder selected in ADR-0005. Scores are compressed into [0, 1] with
a sigmoid so the retrieval-quality gate has a stable threshold to compare
against.
