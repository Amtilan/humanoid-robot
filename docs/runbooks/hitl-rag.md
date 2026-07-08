# HITL smoke test — cortex-rag

Purpose: verify end-to-end that a running robot can (a) accept an
`asr.final` event on NATS, (b) run the grounded-QA chain against the local
LLM/embedder/reranker/vector-store stack, and (c) publish either
`llm.answer` or `llm.rejected` with a meaningful reason.

## Prerequisites (on the robot)

- `nats-server` reachable at `HR_RAG_NATS`.
- `llama-server` running with your chosen model, reachable at
  `HR_RAG_LLM_URL`. The model tag sent through the OpenAI-compat API is
  taken from `HR_RAG_LLM_MODEL`.
- Runtime extras installed:
  ```bash
  uv add "humanoid-robot-adapters-embed-bge[runtime]" \
         "humanoid-robot-adapters-rerank-bge[runtime]" \
         "humanoid-robot-adapters-vector-qdrant[runtime]"
  ```
- A pre-populated Qdrant collection at `HR_RAG_QDRANT_PATH` (default
  `/var/lib/humanoid-robot/qdrant`). Ingestion pipeline lands in Phase 4
  round 3; for smoke you can populate manually against the embedded store.

## Run

```bash
export HR_RAG_NATS=nats://127.0.0.1:4222
export HR_RAG_LLM_URL=http://127.0.0.1:8080
export HR_RAG_LLM_MODEL=qwen3-8b-instruct-q4_k_m
export HR_RAG_QDRANT_PATH=/var/lib/humanoid-robot/qdrant
export HR_RAG_QUESTION="Работает ли робот полностью офлайн?"
uv run python scripts/hitl_rag_smoke.py
```

Expected: `hitl rag smoke: OK` and exit code 0 within ~60 s.

## Debugging

- `nats sub 'llm.>'` in another terminal to observe the answer / rejection.
- If the runner logs `retrieval_verdict=fail_low_coverage`, the corpus in
  Qdrant is too small for the tuned thresholds — either lower them in
  `deploy/config/rag.yaml` or add more chunks.
- `llm.rejected` with `reason=citation_verify_failed` typically means the
  LLM hallucinated a chunk-id — check the llama-server logs for the raw
  JSON output.
