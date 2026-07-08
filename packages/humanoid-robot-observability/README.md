# humanoid-robot-observability

Standard observability wiring shared by every service.

- `configure_logging(...)` — JSON structlog with contextvar binding for
  `correlation_id`, `trace_id`, `span_id`.
- `configure_tracing(...)` — OTel SDK with OTLP exporter (defaults to local
  collector `http://127.0.0.1:4318`).
- `metrics.counter/gauge/histogram(...)` — thin wrappers around
  `prometheus_client` that expose a consistent naming/labels policy.

Everything is opt-in per service: the observability package does not
mutate global state at import time; the service explicitly calls the
configure functions during startup.
