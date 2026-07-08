# humanoid-robot dashboard

React 18 + TypeScript + Vite + Tailwind CSS.  Read-only operator UI for the
cortex-core service.

## Development

```bash
cd web/dashboard
pnpm install
pnpm dev            # opens http://localhost:5173 with /api proxied to :8080
pnpm typecheck
pnpm build
```

Vite proxies `/api/*` calls (including the WebSocket `/api/v1/events/ws`)
to the `cortex-core` service running on `127.0.0.1:8080`, so no CORS
configuration is required in development.

## Pages (round 1)

- **Dashboard** — service info + readiness + adapter-group count.
- **Adapters** — every installed entry-point across every group.
- **Events** — live WebSocket tail of the bus, filterable by subject.

Round 2 will add pages for LLM/RAG tuning, KB manager, robot control,
users, and permissions.
