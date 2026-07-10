"""Built-in safety policies.

Each policy is a `SafetyPolicyPort`.  Compose them with `ChainPolicy` —
the first `deny` wins; `allow` requires all links to allow.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from humanoid_robot.domain.robot import MoveCommand, StopCommand
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


DEFAULT_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "locomotion.move": MoveCommand,
    "locomotion.stop": StopCommand,
}


@dataclass(slots=True)
class PayloadSchemaPolicy:
    """Denies commands whose payload does not match the capability schema.

    ``schemas`` maps a capability to a pydantic model.  Capabilities not
    present in the map pass through — other policies (allow-list,
    velocity, etc.) still apply.  Validation errors are collapsed into
    the first ``msg`` for a compact human-readable reason; the full
    error is logged by the caller if needed.
    """

    schemas: dict[str, type[BaseModel]] = field(
        default_factory=lambda: dict(DEFAULT_PAYLOAD_SCHEMAS)
    )

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        schema = self.schemas.get(request.capability)
        if schema is None:
            return SafetyDecision(
                verdict="allow",
                reason=f"no schema registered for {request.capability!r}",
            )
        try:
            schema.model_validate(request.payload)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            loc = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
            msg = str(first.get("msg", "invalid payload"))
            return SafetyDecision(
                verdict="deny",
                reason=f"schema violation @ {loc}: {msg}"[:200],
            )
        return SafetyDecision(
            verdict="allow", reason=f"payload matches {request.capability} schema"
        )


@dataclass(slots=True)
class ActorRateLimit:
    """Sliding-window budget for one submitter bucket."""

    window_s: float
    max_events: int


@dataclass(slots=True)
class PerActorRateLimitPolicy:
    """Sliding-window rate limit keyed by ``submitter``.

    ``limits`` maps a submitter string to its budget.  If the incoming
    request's submitter is not in the map, ``default`` is used.  Setting
    ``default.max_events`` to 0 fails-closed for unknown actors, which
    matches the platform's overall posture.
    """

    limits: dict[str, ActorRateLimit]
    default: ActorRateLimit
    _events: dict[str, deque[float]] = field(default_factory=dict)

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        submitter = request.submitter
        budget = self.limits.get(submitter, self.default)
        if budget.max_events == 0:
            return SafetyDecision(
                verdict="deny",
                reason=f"actor {submitter!r} has no command budget",
            )
        window = self._events.setdefault(submitter, deque())
        now = time.monotonic()
        cutoff = now - budget.window_s
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= budget.max_events:
            return SafetyDecision(
                verdict="deny",
                reason=(
                    f"actor {submitter!r} exceeded budget: "
                    f"{len(window)}/{budget.max_events} in {budget.window_s:.1f}s"
                ),
            )
        window.append(now)
        return SafetyDecision(
            verdict="allow",
            reason=f"actor {submitter!r} within budget",
        )


@dataclass(slots=True)
class VelocityLimitPolicy:
    """Denies `locomotion.move` commands that exceed configured envelope.

    Any capability other than ``locomotion.move`` allows through so
    higher-capability envelopes (arm gestures, head pose) are governed
    by their own policies.  Combined linear speed uses the L2 norm of
    ``linear_x_mps`` + ``linear_y_mps`` to catch diagonal blow-outs.
    """

    max_linear_speed_mps: float
    max_angular_rate_rps: float
    capability: str = "locomotion.move"

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision:
        if request.capability != self.capability:
            return SafetyDecision(verdict="allow", reason="not a locomotion command")
        try:
            linear_x = _as_float(request.payload.get("linear_x_mps", 0.0))
            linear_y = _as_float(request.payload.get("linear_y_mps", 0.0))
            angular_z = _as_float(request.payload.get("angular_z_rps", 0.0))
        except (TypeError, ValueError):
            return SafetyDecision(
                verdict="deny",
                reason="locomotion.move payload has non-numeric velocity fields",
            )
        speed = math.hypot(linear_x, linear_y)
        if speed > self.max_linear_speed_mps:
            return SafetyDecision(
                verdict="deny",
                reason=(
                    f"linear speed {speed:.2f} m/s exceeds "
                    f"limit {self.max_linear_speed_mps:.2f} m/s"
                ),
            )
        if abs(angular_z) > self.max_angular_rate_rps:
            return SafetyDecision(
                verdict="deny",
                reason=(
                    f"angular rate {abs(angular_z):.2f} rad/s exceeds "
                    f"limit {self.max_angular_rate_rps:.2f} rad/s"
                ),
            )
        return SafetyDecision(verdict="allow", reason="within velocity envelope")


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        msg = "bool is not a valid velocity value"
        raise TypeError(msg)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    msg = f"cannot coerce {type(value).__name__} to float"
    raise TypeError(msg)


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
