# humanoid-robot-adapters-vector-qdrant

`VectorStorePort` on top of Qdrant in local (embedded) mode per ADR-0005.
The adapter needs an `EmbeddingPort` at construction: it uses it to turn
raw chunk text into vectors on upsert and to embed the search query.

## Installation

```bash
uv add "humanoid-robot-adapters-vector-qdrant[runtime]"
```

The `runtime` extra pulls `qdrant-client`; storage is a local directory
(`local_path`) so no separate Qdrant server is required.
