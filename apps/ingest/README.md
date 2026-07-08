# cortex-ingest

Batch ingestion CLI: walks a directory, parses each file with the parser
registered for its extension, splits into chunks, embeds them, and upserts
into the vector store. Uses the same `ChunkerPort` / `EmbeddingPort` /
`VectorStorePort` contracts as the RAG runner, so the two subsystems can
never drift.

## Usage

```bash
cortex-ingest run --config /etc/humanoid-robot/ingest.yaml --dir /var/lib/humanoid-robot/kb
```

The directory tree is walked recursively; hidden files (`.git`, `.venv`
etc.) are skipped. Progress is logged in structured JSON.

## Incremental updates

Idempotent by construction: every chunk id is the hash of
`(source_id, ordinal, content)`. Upserting the same content twice is a
no-op. Changed content changes the `source_id` (content-addressed) so the
previous version's chunks are orphaned; the operator can call
`cortex-ingest gc --config …` to prune orphaned chunks (planned).

Delta watching (`inotify`) is planned for round 4.
