"""In-memory `EventBusPort` for deterministic tests.

Semantics:
    - `publish` fans out synchronously to matching subscribers before returning
      (tests can `await bus.publish(...)` then assert against a spy).
    - Subject matching supports NATS-style `*` (one token) and `>` (rest).
    - `published` keeps a full history for assertions.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import cast

from humanoid_robot.events import BaseEvent
from humanoid_robot.ports.event_bus import EventBusPort, EventHandler, Subscription


@dataclass(slots=True)
class _Sub:
    pattern: str
    handler: EventHandler
    cancelled: bool = False

    async def cancel(self) -> None:
        self.cancelled = True


@dataclass(slots=True)
class InMemoryEventBus(EventBusPort):
    """Deterministic in-memory pub/sub for tests."""

    published: list[BaseEvent] = field(default_factory=list)
    _subs: list[_Sub] = field(default_factory=list)
    _closed: bool = False

    async def publish(self, event: BaseEvent) -> None:
        if self._closed:
            msg = "bus is closed"
            raise RuntimeError(msg)
        self.published.append(event)
        for sub in self._live_subs_for(event.subject):
            await sub.handler(event)

    async def subscribe(
        self,
        subject_pattern: str,
        handler: EventHandler,
        *,
        durable_name: str | None = None,
    ) -> Subscription:
        if self._closed:
            msg = "bus is closed"
            raise RuntimeError(msg)
        sub = _Sub(pattern=subject_pattern, handler=handler)
        self._subs.append(sub)
        return cast(Subscription, sub)

    async def close(self) -> None:
        self._closed = True
        for sub in self._subs:
            await sub.cancel()

    # ---- helpers for tests ---------------------------------------------------

    def _live_subs_for(self, subject: str) -> Iterable[_Sub]:
        for sub in self._subs:
            if sub.cancelled:
                continue
            if _subject_matches(sub.pattern, subject):
                yield sub

    def clear(self) -> None:
        self.published.clear()


def _subject_matches(pattern: str, subject: str) -> bool:
    """NATS-style matcher: `*` = one token, `>` = rest, `.` = separator."""
    # Convert NATS wildcards to fnmatch equivalents.
    # NATS `.` is a token separator (not a regex meta), so we translate token
    # by token instead of using fnmatch on the raw string.
    p_tokens = pattern.split(".")
    s_tokens = subject.split(".")
    for i, ptok in enumerate(p_tokens):
        if ptok == ">":
            return i <= len(s_tokens)
        if i >= len(s_tokens):
            return False
        if ptok == "*":
            continue
        if not fnmatch.fnmatchcase(s_tokens[i], ptok):
            return False
    return len(p_tokens) == len(s_tokens)
