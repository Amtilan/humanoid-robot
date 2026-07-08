# 0001 — Hexagonal + DDD + Event-Driven core style

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: platform maintainers

## Context

The platform must support many robot models over 10+ years. Concrete
technologies — the ASR model, the LLM runtime, the vector store, the robot
transport — will change several times. If the core is tightly coupled to any
of them, we will end up doing full rewrites.

We also need parts of the system to work independently: a robot adapter
process crashing should not take down the RAG server; a plugin should not need
to know how the event bus is implemented.

## Decision

We adopt a **layered composite style**:

1. **Domain-Driven Design (tactical)** to structure the codebase into bounded
   contexts: `voice`, `knowledge`, `robot`, `identity`, `telemetry`. Each
   context owns its entities, value objects, and language.
2. **Hexagonal (Ports & Adapters)** to isolate the domain from infrastructure.
   Every external capability (ASR, LLM, TTS, vector store, robot hardware,
   event bus) is exposed as a `typing.Protocol` (a *port*). Concrete
   *adapters* implement those protocols and live outside the domain.
3. **Event-Driven** for coordination across processes and contexts. Domain
   events (`AsrFinal`, `RobotCommandRequested`, `SystemHealth`, ...) flow
   through the event bus; no service calls another synchronously except via
   an explicit port.
4. **Clean Architecture dependency rule**, enforced by `import-linter`:
   `domain ← application ← adapters ← infrastructure`. The domain imports
   nothing from FastAPI, Qdrant, NATS, etc.

CQRS is **not** applied blanket. It is used only where it earns its keep
(audit log, plugin lifecycle state, telemetry read-model). This preserves the
simplicity of most CRUD flows.

## Alternatives considered

| Style | Pros | Cons | Verdict |
|---|---|---|---|
| Layered N-tier only | Familiar | Blurs domain and infra, tests need real infra | ✗ |
| Pure microservices from day 1 | Independent deploy, scale | Overkill for a single edge host; ops burden | ✗ |
| Pure DDD tactical without ports | Rich domain | Domain still couples to infra without ports | ✗ (partial) |
| Actor model (dataflow, Erlang-style) | Great for concurrent behaviour | Python actor libraries are anaemic; harder to reason about | ✗ |
| Hexagonal + DDD + Event-Driven | Testable, swappable infra, weakly coupled contexts | Small overhead in interface definitions | ✅ chosen |
| ECS (entity-component-system) | Good for game engines / dense simulation | Wrong shape for an AI/RAG platform | ✗ |

## Consequences

- Every third-party dependency (ASR, LLM, vector DB, robot SDK, secrets store)
  sits behind a Port. Domain code has *zero* imports from these libraries.
- Tests run in milliseconds because domain and application layers use in-
  memory fakes shipped in `humanoid-robot-testing`.
- A new adapter (e.g. `unitree_go2`, `ros2`, `esp32_serial`) is a self-
  contained package; the core does not change.
- Cross-context coordination is asynchronous and observable through the event
  stream, which makes tracing and replay natural.
- Slight upfront cost: every new capability requires (a) a domain model,
  (b) a port, and (c) at least one adapter. This is intentional friction.
