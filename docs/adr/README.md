# Architecture Decision Records (ADRs)

Every non-trivial architectural or technology choice ships here as an ADR
before the corresponding code lands. Format is
[Michael Nygard's](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions.html)
with a small addition (alternatives table).

## Rules

1. New ADRs are numbered sequentially (`NNNN-slug.md`).
2. An ADR is **immutable once merged**. To change a decision, add a new ADR
   that supersedes the old one (link both ways).
3. Every ADR must include: **Context**, **Decision**, **Alternatives**,
   **Consequences**, **Status**.

## Statuses

- `Proposed` — under review, not yet applied.
- `Accepted` — the decision is in effect.
- `Superseded by NNNN` — obsolete; see the new ADR.
- `Deprecated` — no longer applicable; no successor.

## Index

- [0000 — Record architecture decisions](0000-record-architecture-decisions.md)
- [0001 — Hexagonal + DDD + Event-Driven core style](0001-hexagonal-ddd-event-driven.md)
- [0002 — Monorepo with uv workspaces](0002-monorepo-uv-workspaces.md)
- [0003 — NATS + JetStream as the platform event bus](0003-nats-jetstream-event-bus.md)
- [0004 — HW-first voice pipeline (XMOS XVF3800 primary)](0004-hw-first-voice-pipeline.md)
- [0005 — Offline AI stack lock-in (mid-2026)](0005-ai-stack-lock-in.md)
