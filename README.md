# humanoid-robot

**Offline-first AI platform for autonomous humanoid robots.**

A production-grade edge platform that runs entirely on the robot: local speech
recognition, local LLM, retrieval-augmented answers strictly grounded in your
documents, and a Robot Adapter Layer so the same business logic drives any
robot model (Unitree G1, Go2, ROS 2, ESP32, and beyond).

## Design goals

- **Runs offline.** No OpenAI, no Claude, no Gemini. Internet is used only for
  OTA updates, model downloads, and telemetry export.
- **Universal.** Add a new robot by writing one adapter. The rest of the code
  never changes.
- **Modular.** Voice, RAG, LLM, plugins are ports; concrete implementations are
  hot-swappable.
- **Grounded.** Answers are constrained to what the retrieved documents say —
  four independent guardrails ensure the LLM cannot invent facts.
- **Enterprise-grade operations.** OTA with rollback, RBAC, structured logs,
  Prometheus/OpenTelemetry, signed artefacts.

## Architecture at a glance

- **Language / runtime**: Python 3.12, FastAPI, Pydantic v2, `uv` workspaces.
- **Style**: Hexagonal (Ports & Adapters), DDD (bounded contexts),
  Event-Driven (NATS + JetStream).
- **Deployment**: hybrid — systemd on the host for system-critical services,
  Docker for AI workers (`nvidia-container-runtime`).
- **AI stack**: `faster-whisper large-v3-turbo` (ASR), `Qwen 2.5 7B` via
  `llama.cpp` (LLM), Piper (TTS), BGE-M3 (embeddings), Qdrant (vector DB),
  DeepFilterNet2 + WebRTC AEC3 + Silero VAD + openWakeWord (voice pipeline).

Rationale for every choice above lives under [`docs/adr/`](docs/adr/).

## Repository layout

```
apps/         Deployable services (core orchestrator, AI workers, robot adapter runner)
packages/     Libraries — domain, events, ports, adapters, testing kit, SDKs
plugins/      First-party plugins (navigation, home assistant, telegram, mqtt, ...)
web/          Web UI (React 18 + TypeScript + Vite + Tailwind + shadcn/ui)
deploy/       Systemd units, Docker compose, Mender OTA config, Ansible, flashing
docs/         Architecture, ADRs, C4 diagrams, event schemas, runbooks
scripts/      Dev/ops helpers
tools/        In-house tooling that is not part of runtime
```

## Getting started (developer machine)

Prerequisites: **Python 3.12**, [`uv`](https://docs.astral.sh/uv/) 0.11+.

```bash
uv sync --all-packages --dev            # install workspace + dev deps
uv run pytest --cov                      # run tests
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run lint-imports                      # architecture contracts
uv run pre-commit install                # gate future commits
```

Deployment steps (Jetson, robot, OTA) live in [`deploy/`](deploy/) and
[`docs/runbooks/`](docs/runbooks/).

## Contributing

- All changes go through PRs. Conventional Commits required (enforced by
  commitizen). Squash-merge is the default.
- Architecture decisions must ship as an ADR under `docs/adr/` before code
  lands.
- Tests are non-optional. Domain and application layers require 80%+ coverage.

## License

Apache-2.0. See [LICENSE](LICENSE).
