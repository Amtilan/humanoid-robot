# Contributing

## Ground rules

- Every change goes through a PR. No direct pushes to `main`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
  Enforced by `commitizen` (pre-commit hook).
- Non-trivial architectural or technology changes require an ADR under
  [`docs/adr/`](docs/adr/) **before** the PR that implements them.
- Tests are non-optional. New behaviour needs a test; new port needs a
  contract test in `humanoid-robot-testing`.

## Local checks

Before opening a PR, run:

```bash
uv sync --all-packages --dev
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run lint-imports
uv run pytest --cov
```

Faster path: install pre-commit hooks once and let them gate every commit:

```bash
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

## Adding a new port

1. Add the `Protocol` under
   `packages/humanoid-robot-ports/src/humanoid_robot/ports/<area>.py`.
2. Add a fake in
   `packages/humanoid-robot-testing/src/humanoid_robot/testing/`.
3. Add a domain-level test that pins the contract.
4. Adapters implementing the port live in a separate package under
   `packages/humanoid-robot-adapters-<name>/`.

## Adding a new adapter

1. Create `packages/humanoid-robot-adapters-<slug>/` with its own
   `pyproject.toml`.
2. Register via `[project.entry-points."humanoid_robot.robot_adapters"]` for
   robot adapters, or the equivalent group for other kinds of adapters.
3. Implement the ports declared in `humanoid-robot-ports`.
4. Ship the contract test suite from `humanoid-robot-testing`.
5. Document limitations in the package README.
