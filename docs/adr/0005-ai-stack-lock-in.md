# 0005 — Offline AI stack lock-in (mid-2026)

- **Status**: Accepted
- **Date**: 2026-07-08
- **Supersedes / updates**: initial informal picks in the Phase 0 architecture
  brief (Qwen 2.5 7B, faster-whisper large-v3-turbo, Piper, BGE-M3, Qdrant,
  llama.cpp) — this ADR updates the LLM choice and confirms the rest.

## Context

The platform runs fully offline on NVIDIA Jetson Orin NX 16 GB (JetPack 6.x
target). Budget: 12 GB VRAM active across LLM + ASR + TTS + embeddings +
reranker + vector DB. Primary language Russian, secondary English. Project
license is Apache-2.0 — every bundled model weight must be either
permissive (Apache-2.0, MIT) or explicitly commercial-friendly under a
license we accept.

Model landscape has moved substantially since early 2024:

- **Qwen 3** shipped Apr 2025 under Apache-2.0 — supersedes Qwen 2.5 for
  general-purpose small-model use.
- **Whisper large-v3-turbo** shipped Oct 2024 under MIT — remains the
  offline ASR reference; no Whisper v4 confirmed as of mid-2026.
- **Kokoro-82M** shipped Jan 2025 under Apache-2.0 (English-only) —
  meaningful for the EN track; Russian voice not officially released.
- **Gemma license** confirmed as a bespoke Google license (not Apache);
  incompatible with our Apache purity goal.
- **Silero commercial models, Jina Embeddings, Coqui XTTS v2, F5-TTS**
  confirmed non-commercial or non-Apache — all rejected.

## Decisions

### LLM — Qwen 3 8B Instruct Q4_K_M (GGUF), Apache-2.0

- ~5 GB VRAM at Q4_K_M.
- Native "thinking / non-thinking" toggle, Hermes-style tool-calling,
  128k context.
- Russian quality is the strongest under Apache — Qwen 3 was trained on
  119 languages.
- **Fallback for low-latency**: Qwen 3 4B Instruct.
- **Alternative "reasoning-heavy"**: DeepSeek R1 Distill Qwen 8B (MIT) —
  wired as an opt-in in config, not the default; long CoT doubles our
  RAG-answer latency.

Rejected:
- **Qwen 2.5 7B** — Qwen 3 8B strictly dominates.
- **Gemma 3 / Gemma 4** — bespoke license; downstream Apache-2.0
  redistribution of derivatives is legally muddy.
- **Phi-4 / Phi-4-mini** — Russian weak due to tokenizer.
- **Llama 3.3 / Llama 4** — Llama Community License, acceptable-use
  policy, non-Apache; Llama 4 Scout also busts VRAM.
- **Mistral Small 3 24B** — ~14 GB at Q4, does not fit.
- **Ministral 8B** — Mistral Research License (non-commercial default).
- **Nemotron-Mini-4B-Instruct, Arctic Instruct** — proprietary-adjacent or
  MoE-scale, not portable.

### LLM runtime — llama.cpp CUDA server (primary)

- Stable on JetPack 6.x with CUDA 12.2+.
- GGUF is the format we already produce for every model choice.
- ~30–40 tok/s on Qwen 3 8B Q4 on Orin NX.
- Server exposes an OpenAI-compat HTTP API — trivially replaceable if we
  ever swap runtimes.

Fallback:
- **MLC-LLM** — Apache-2.0, TVM Relax compile, fastest INT4 path when it
  builds. Compilation friction is real.

Rejected:
- **TensorRT-LLM on Jetson** — GA landed but every model quant is a new
  engine build; ops burden too high for our team size right now.
  Revisit for Phase 6 once fleet is stabilized.
- **vLLM** — awkward on Jetson unified memory; 1.3–1.5× llama.cpp VRAM.
- **Ollama** — just a wrapper; run llama.cpp `server` directly.

### ASR — faster-whisper large-v3-turbo INT8 (CT2, streaming-wrapped)

- ~1.6 GB VRAM.
- Partial hypothesis latency ~300–400 ms with 500 ms chunks + Silero VAD
  segmentation.
- MIT license.
- Streaming implemented as a chunked wrapper in the ASR worker (Silero VAD
  segmentation + partial decodes every 300 ms + final decode on
  utterance end).

Optional RU-specialist head:
- **GigaAM-v2 (Sber, MIT)** — best pure-Russian ASR available under a
  permissive licence; English not supported. Dispatch by detected
  language: RU → GigaAM-v2, else → Whisper. Off by default in Phase 3;
  enable if operator KPIs demand it.

Rejected:
- **NVIDIA Parakeet-TDT / Canary** — English (or western-only), no
  Russian.
- **SenseVoice** — 50 langs incl. RU but WER worse than Whisper on RU.
- **Silero STT commercial-tier** — non-commercial license blocks Apache
  redistribution.

### TTS — Piper (RU + EN) primary, Kokoro-82M optional EN

- **Piper** — MIT, ONNX runtime, ~60 MB, 10× real-time on Orin NX CPU
  alone. First-byte latency ~50 ms. RU voices `ru_RU-*` (denis, dmitri,
  irina, ruslan) — usable, robotic. Uniform stack across languages.
- **Kokoro-82M v1** — Apache-2.0, natural-sounding English at 82 M params.
  Optional EN track for premium naturalness; no official RU voice as of
  mid-2026.

Rejected:
- **Silero TTS** — non-commercial.
- **Coqui XTTS v2** — Coqui Public Model License (non-commercial after
  Coqui shutdown Jan 2024).
- **F5-TTS** — CC-BY-NC-4.0.
- **StyleTTS 2, MetaVoice, Sesame CSM** — either EN-only, unmaintained,
  or too heavy alongside the LLM.

### Embeddings — BGE-M3

- MIT.
- Dense + sparse + ColBERT multi-vector in one forward — matches Qdrant
  hybrid retrieval without a second model.
- 100+ languages; strong RU.
- ~1 GB VRAM.

Rejected:
- **Jina Embeddings v3 / v4** — CC-BY-NC-4.0.
- **E5-Mistral-7B-Instruct** — busts VRAM alongside the LLM.
- **BGE-Multilingual-Gemma2** — Gemma license.

Apache-only alternative if we ever tighten purity:
- **Snowflake Arctic Embed v2** (Apache-2.0, ~570 M) — competitive with
  BGE-M3 on MIRACL and lighter.

### Reranker — BGE-Reranker v2-m3

- MIT, multilingual cross-encoder, ~600 MB, ~100 ms/pair on Jetson.

Apache-only alternative:
- **mxbai-rerank-large-v2** — Apache-2.0, strong but English-leaning.

Rejected:
- **Jina Reranker v2 / v3** — non-commercial.

### Vector DB — Qdrant (embedded / local mode)

- Apache-2.0.
- Dense + sparse hybrid matches BGE-M3.
- Payload filters (per-tenant, per-source).
- Snapshotting for backup/DR.
- Path to Qdrant cluster / leaf-node for fleet mode with no code change.

Rejected:
- **LanceDB** — matured a lot in 2025 but weaker on live hybrid + payload
  filters vs. Qdrant.
- **Milvus Lite** — no sparse vectors in Lite; thin ARM story.
- **pgvector** — Postgres is heavy for a robot; skip unless we already
  run PG for other reasons.
- **sqlite-vec** — no hybrid, no per-tenant story, no snapshotting.

## Language routing

Default language = Russian. Detection strategy for the mixed-language
subset of users:

- ASR path: run Silero VAD → chunk → Whisper large-v3-turbo with
  `--language ru` default; `condition_on_previous_text=False` on the first
  chunk to allow Whisper's own language detection to override on strongly
  non-RU audio (English utterances).
- TTS path: pick Piper voice by response language (either explicit from
  the RAG-answer JSON or by content-based `fasttext` detection).

## VRAM budget (worst-case, in-use simultaneously)

| Component | VRAM |
|---|---|
| Qwen 3 8B Q4_K_M + KV cache | ~5.5 GB |
| Whisper large-v3-turbo INT8 (CT2) | ~1.6 GB |
| BGE-M3 (dense+sparse+ColBERT) | ~1.0 GB |
| BGE-Reranker v2-m3 | ~0.6 GB |
| Piper (CPU-only) | 0 GB VRAM |
| Silero VAD (ONNX, CPU) | 0 GB VRAM |
| DeepFilterNet2 (ONNX, CPU) | 0 GB VRAM |
| Slack / KV growth | ~1.0 GB |
| **Total active** | **~9.7 GB / 16 GB** |

Kokoro-82M optional: ~200 MB more CPU RAM, 0 GB VRAM.

## Consequences

- Every subsystem consumes its port and can be swapped without touching
  the domain — LLM behind `LlmPort`, ASR behind `AsrPort`, etc.
- Model artefacts live in a content-addressable model repository shipped
  via OTA (see planned ADR-0011). Weights are not committed to git; the
  `*.gguf`, `*.onnx`, `*.pt` patterns in `.gitignore` enforce that.
- Config knob per port names the runtime + model (`llm.model_id =
  "qwen3-8b-instruct-q4-k-m"`, `asr.model_id = "whisper-large-v3-turbo"`).
- ADR-0004 (HW-first voice) governs how the mic input reaches the ASR
  worker; this ADR governs what the ASR worker does with it.
- A future ADR may lift Qwen 3 to Qwen 4 or promote GigaAM-v2 to primary
  RU ASR — both are model-swap-only changes, not architectural changes.

## Sourcing note

The stack decisions above draw on the model landscape as of the assistant's
training cutoff (January 2026). Anything released Feb–Jul 2026 (a
hypothetical Qwen 4, Whisper v4, Kokoro-RU, Jina v5, TensorRT-LLM Jetson
GA update) is not accounted for and should be verified against upstream
release notes before locking specific model versions in production
manifests.
