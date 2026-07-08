# 0003 — NATS + JetStream as the platform event bus

- **Status**: Accepted
- **Date**: 2026-07-08

## Context

The platform is a collection of processes (`cortex-core`, `asr-worker`,
`llm-worker`, `tts-worker`, `robot-adapter`, plugins) that must coordinate:

- fire-and-forget signals (`SpeechDetected`, `WakeWordTriggered`)
- request/reply commands (`RobotCommandRequested → RobotCommandResulted`)
- durable audit and telemetry streams that survive restarts
- fleet-level replay for post-mortem analysis (later phase)

The bus must run comfortably on an edge host (Jetson Orin NX, 16 GB RAM), be
usable from Python and from external plugins (JS, Go, C++), and support
authentication, per-service access control, and TLS.

## Decision

Use **NATS** as the messaging core, with **JetStream** enabled for durable
streams. Reasons:

- **Footprint**: single Go binary (~10 MB), ~20 MB RAM idle. Runs as a
  systemd service on the host.
- **Semantics**: ephemeral pub/sub for hot signals, JetStream persistent
  streams for durable events (audit, telemetry, plugin log). Same broker,
  same subjects.
- **Auth**: JWT / nkey with per-account and per-subject ACLs — plugins get
  narrowly-scoped tokens.
- **Ecosystem**: first-class Python (`nats-py`), Go, Rust, JS/TS SDKs.
- **Fleet path**: NATS cluster mode + leaf-nodes turns each robot into a
  leaf that syncs a subset of subjects with a central hub. No code changes
  when we scale from one robot to a fleet.

Every message crossing a process boundary is a subclass of
`humanoid_robot.events.BaseEvent` carrying `correlation_id`, `causation_id`,
`trace_id`, and a JSON-schema-validated payload.

## Alternatives considered

| Broker | Pros | Cons | Verdict |
|---|---|---|---|
| **NATS + JetStream** | Tiny, cluster-ready, JWT/ACL, streams+KV, ecosystem | Learning curve for JetStream semantics | ✅ chosen |
| MQTT (mosquitto) | IoT standard, ubiquitous | No replay in v3.1.1; MQTT 5 headers are fine but streams are absent; ACLs coarser | ✗ |
| Redis Streams / Pub/Sub | Familiar | RAM-heavy for persistence; no fine-grained ACL; ops burden | ✗ |
| RabbitMQ / AMQP | Feature-rich | Erlang runtime; heavier; overkill for edge | ✗ |
| Kafka / Redpanda | High-throughput streaming | Kafka: JVM, heavy. Redpanda: compact, but still too much for one edge host | ✗ (revisit for fleet backbone only) |
| CycloneDDS (existing on Unitree) | Native to ROS 2, low-latency multicast | Great for hardware-side; bad for plugins/JS/TS/user apps; heavy multicast on shared LAN | 🟡 kept for robot-adapter ↔ robot HW only |
| In-process asyncio queue only | Zero infra | Single process; useless once we split workers | 🟡 kept as `InMemoryEventBus` for tests |
| gRPC streaming (no broker) | Type-safe | Point-to-point; no fan-out; every consumer needs to know producers | ✗ |

## Consequences

- The `EventBusPort` (see `humanoid-robot-ports`) has two implementations:
  in-process for tests, NATS for prod. Application code depends only on the
  port.
- Every event class carries a `subject` (NATS subject) and a `schema_version`.
  Consumers subscribe to subject patterns like `asr.*` or `robot.>`.
- Durable streams (`security.audit`, `system.ota.*`, `robot.telemetry`) are
  configured in `deploy/nats/streams.yaml` and applied at boot by the
  updater.
- We accept the operational cost of running one broker daemon on each robot,
  in exchange for a uniform, observable, and scalable substrate.
- If NATS ever becomes unfit (unlikely at this scale), the migration path is
  a new `EventBusPort` adapter — no code change in producers or consumers.
