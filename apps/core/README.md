# cortex-core

Main orchestrator — long-running FastAPI process that owns the DI container,
brings up the event bus, wires up the future robot/voice/knowledge use
cases, and serves the HTTP + WebSocket API for operator UIs.

## Running

Standard `uv` workflow — no need to build wheels for local dev:

```bash
uv run cortex-core                           # dev server, reload off
uv run cortex-core --config config/dev.yaml  # explicit config
```

Under systemd the process is started by `deploy/systemd/cortex-core.service`
which reads its runtime configuration from
`/etc/humanoid-robot/config.yaml`.

## Composition root

`cortex_core.container.AppContainer` is the single Singleton-like object in
the platform. It is created once from `main.py`, its lifecycle drives every
service, and the FastAPI app depends on it exclusively — no ad-hoc
`get_instance()` in business code.

## Endpoints (Phase 1)

- `GET /api/v1/system/info` — version, robot manifest (once available)
- `GET /api/v1/system/health/live` — liveness (always fast)
- `GET /api/v1/system/health/ready` — readiness (bus up, adapters ready)
- `GET /metrics` — Prometheus scrape endpoint
- `WS  /api/v1/events` — server-side broadcast of platform events
