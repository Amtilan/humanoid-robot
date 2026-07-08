# cortex-rag

Grounded-QA orchestrator. Subscribes to `asr.final` on NATS, retrieves
supporting chunks from the vector store, calls the LLM with a strict
grounded-answer JSON grammar, verifies citations against the retrieved
chunks, runs a grounding-judge second pass, and publishes either
`llm.answer` or `llm.rejected`.

## Pipeline

```
asr.final ──► Retriever (dense + rerank)
                │
                ▼
        Retrieval Quality Gate
                │
     pass       │       fail → llm.rejected
                ▼
     LLM Grounded QA (JSON grammar)
                │
                ▼
     Citation Verifier
                │
     pass       │       fail → retry(1) → llm.rejected
                ▼
     Grounding Judge (LLM-as-judge)
                │
     supported  │  partial/unsupported → llm.rejected
                ▼
              llm.answer
```

## Configuration

`deploy/config/rag.yaml` is the reference file; overrides via `HR_RAG__*`
env vars. Every port slot uses entry-point resolution the same way the
voice runner does.
