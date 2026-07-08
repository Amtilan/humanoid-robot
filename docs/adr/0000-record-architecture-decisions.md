# 0000 — Record architecture decisions

- **Status**: Accepted
- **Date**: 2026-07-08
- **Deciders**: platform maintainers

## Context

We are building a long-lived (10+ year horizon) edge AI platform that will
outlive its authors. Decisions taken today — event bus, LLM runtime, robot
adapter interfaces — will shape the platform's ceiling. New contributors need
to understand *why* things are the way they are, without archaeology through
Slack and PR comments.

## Decision

We adopt [Architecture Decision Records (ADRs)](
https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions.html)
as the sole place where non-trivial architectural choices are documented. An
ADR is a Markdown file under `docs/adr/`, numbered sequentially, following the
template used by this file.

Every architectural decision:

1. Ships as an ADR **before** the code that implements it lands.
2. Lists **alternatives** considered, with concrete pros/cons.
3. Is immutable once merged. A change is a new ADR that supersedes the old.

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| ADRs | Lightweight, in-repo, reviewable via PR, no tooling needed | Requires discipline | ✅ chosen |
| Confluence / Notion pages | Rich formatting, comments | Drifts from code, expires with vendor | ✗ |
| Google Docs | Familiar | Not diffable, no version, external | ✗ |
| RFCs (rustc-style) | More discussion structure | Overkill for a project of our size | ✗ (not yet) |
| No ADRs — rely on PR history | Zero overhead | PRs get lost; new hires can't find the *why* | ✗ |

## Consequences

- Every non-trivial PR requires either an ADR reference or a new ADR.
- Reviewers block PRs that skirt this. This is a hard rule.
- We accept a small productivity tax on writing ADRs in exchange for
  long-term maintainability.
