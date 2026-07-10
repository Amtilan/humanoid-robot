"""Safety policy port.

The safety gate sits between higher-level orchestrators (LLM, behavior
tree, plugins) and the concrete robot adapter.  It converts a
`robot.command.requested` into either an allowed command or a
`safety.command.denied` event.  Policies must be **fail-closed** — any
unclassified command is denied.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["allow", "deny"]


class SafetyRequest(BaseModel):
    """A command under review by the safety policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: str
    capability: str
    payload: dict[str, Any]
    submitter: str = "unknown"


class SafetyDecision(BaseModel):
    """The policy's answer for a single command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Verdict
    reason: str = Field(min_length=1, max_length=200)


@runtime_checkable
class SafetyPolicyPort(Protocol):
    """Policies are pure functions of state + request → decision."""

    async def evaluate(self, request: SafetyRequest) -> SafetyDecision: ...


__all__ = [
    "SafetyDecision",
    "SafetyPolicyPort",
    "SafetyRequest",
    "Verdict",
]
