# humanoid-robot-domain

Pure domain layer for the humanoid-robot platform.

**Rules**:
- No I/O (no `open`, no HTTP, no databases, no `asyncio`).
- No infrastructure imports (no FastAPI, no Qdrant, no NATS).
- Only stdlib + `pydantic`.
- Every module here must be safely importable from any other layer, including
  developer laptops without CUDA / robot hardware.

Enforced by `import-linter` contracts in the root `pyproject.toml`.
