# 0002 — Monorepo with uv workspaces

- **Status**: Accepted
- **Date**: 2026-07-08

## Context

The platform is one product delivered on many robots. Its parts —
domain, ports, adapters, event schemas, plugins, deployable apps — evolve
together. A change to a Port must land in the same commit as the adapter and
tests that adopt it. We also want a single CI configuration, one linter
setup, one dependency resolver.

## Decision

Monorepo with **`uv` workspaces**. The root `pyproject.toml` declares
`[tool.uv.workspace] members = ["packages/*", "apps/*", "plugins/*"]`. Every
member ships its own `pyproject.toml` with `hatchling` as build backend and
depends on other members via `[tool.uv.sources]  name = { workspace = true }`.

The whole workspace is installed and tested with:

```bash
uv sync --all-packages --dev
uv run pytest
```

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| Multi-repo per package | Independent versioning, small blast radius | Cross-cutting refactors span many PRs; version drift; heavy tooling | ✗ |
| Monorepo with Poetry workspaces | Established | Poetry workspaces are slow (Python resolver), no `--all-packages`, GitHub Actions caching worse | ✗ |
| Monorepo with pip + editable installs (`pip install -e ...`) | Zero-dep | No unified lock, easy to drift between machines | ✗ |
| Monorepo with Nx / Bazel | Fine-grained cache, cross-language builds | Massive tooling and learning curve; overkill for Python-first project | ✗ |
| Monorepo with **uv workspaces** | Native to `uv` (Rust, fast), single lock, `--all-packages` sync, cache-friendly in CI, PEP 621 native | Still young (2025 GA); Python-only | ✅ chosen |

## Consequences

- One `uv.lock` is committed; developer machines get reproducible resolves.
- CI installs once per job with `uv sync --all-packages --dev` and caches
  the whole `~/.cache/uv` directory.
- Removing a package means deleting a directory and re-running `uv sync`.
- Publishing releases to PyPI is per-package but automated by a single tag on
  the root repo.
- We are betting on `uv` continuing to mature; if it stalls, migrating back to
  Poetry or hatch is mechanical (`pyproject.toml`s already use PEP 621).
