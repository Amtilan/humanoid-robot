# humanoid-robot-events

Central event catalog. **Every** cross-process message carries a subclass of
`humanoid_robot.events.BaseEvent`, with:

- `event_id` — unique per emission
- `schema_version` — integer, bumped on breaking change
- `occurred_at` — timezone-aware UTC
- `correlation_id` — the causal chain
- `causation_id` — the parent event that triggered this one, if any
- `trace_id`, `span_id` — optional OpenTelemetry context propagation

## Subjects

Events publish to hierarchical NATS subjects, e.g. `asr.final`,
`robot.command.requested`. Schema versioning is per event class.

## Compatibility policy

- Additive changes (new optional fields): patch bump, same `schema_version`.
- Breaking changes: increment `schema_version`, keep old class as deprecated
  alias for **two minor releases**, publish a migrator.

## Emitting JSON schemas

`uv run python -m humanoid_robot.events.export_schemas` writes all schemas to
`build/schemas/` for use by non-Python consumers.
