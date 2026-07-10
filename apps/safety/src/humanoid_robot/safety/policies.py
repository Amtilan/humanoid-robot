"""Built-in safety policies.

Each policy is a `SafetyPolicyPort`.  Compose them with `ChainPolicy` —
the first `deny` wins; `allow` requires all links to allow.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from humanoid_robot.ports import SafetyDecision, SafetyPolicyPort, SafetyRequest
from humanoid_robot.safety.estop import EStopState


@dataclass(slots=True)
class EStopPolicy:
    """Denies every command while e-stop is engaged."""

    estop: EStopState

    async def evaluate(self, _request: SafetyRequest) -> SafetyDecision:
        if await self.estop.engaged():
            return SafetyDecision(verdict="deny", reason="e-stop engaged")
        return SafetyDecision(verdict="allow", reason="e-stop released")


@dataclass(slots=True)
class KnownCapabilitiesPolicy:
    """Denies commands whose capability is not on the allow-list.

    Fail-closed — an empty allow-list denies everything.
    """

    allowed: frozenset[str]

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        if request.capability in self.allowed:
            return SafetyDecision(verdict="allow", reason="capability allowed")
        return SafetyDecision(
            verdict="deny",
            reason=f"capability {request.capability!r} not allow-listed",
        )


@dataclass(slots=True)
class RateLimitPolicy:
    """Sliding-window rate limit per capability.

    Prevents runaway loops (e.g. LLM hallucinating a burst of commands).
    """

    window_s: float
    max_events: int
    _events: dict[str, deque[float]] = field(default_factory=dict)

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        window = self._events.setdefault(request.capability, deque())
        now = time.monotonic()
        cutoff = now - self.window_s
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.max_events:
            return SafetyDecision(
                verdict="deny",
                reason=(
                    f"rate limit exceeded: {len(window)}/{self.max_events} in {self.window_s:.1f}s"
                ),
            )
        window.append(now)
        return SafetyDecision(verdict="allow", reason="within rate limit")


@dataclass(slots=True)
class ChainPolicy:
    """Composite policy — first `deny` wins.

    All links must allow for the composite to allow.  If the chain is
    empty the composite denies (fail-closed).
    """

    links: tuple[SafetyPolicyPort, ...]

    def __init__(self, links: Iterable[SafetyPolicyPort]) -> None:
        self.links = tuple(links)

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        if not self.links:
            return SafetyDecision(verdict="deny", reason="no safety policies configured")
        for link in self.links:
            decision = await link.evaluate(request)
            if decision.verdict == "deny":
                return decision
        return SafetyDecision(verdict="allow", reason="all safety policies allowed")
