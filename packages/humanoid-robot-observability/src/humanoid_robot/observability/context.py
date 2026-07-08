"""Context propagation — correlation id + trace ids via contextvars."""

from __future__ import annotations

from contextvars import ContextVar

_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def bind_correlation_id(value: str) -> None:
    """Bind the current async context to a correlation id."""
    _CORRELATION_ID.set(value)


def clear_context() -> None:
    """Reset all context vars managed by this module."""
    _CORRELATION_ID.set(None)


def current_context() -> dict[str, str]:
    """Snapshot the current context for logging/tracing enrichment."""
    ctx: dict[str, str] = {}
    cid = _CORRELATION_ID.get()
    if cid is not None:
        ctx["correlation_id"] = cid
    return ctx
