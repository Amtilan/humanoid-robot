"""Strongly-typed identifiers.

We use `NewType` rather than plain `str` so mypy catches mixing up IDs at
call sites (a `RobotId` passed where a `SessionId` is expected is a bug).
Values are opaque strings — callers must not parse them.
"""

from __future__ import annotations

import uuid
from typing import NewType

CorrelationId = NewType("CorrelationId", str)
SessionId = NewType("SessionId", str)
UtteranceId = NewType("UtteranceId", str)
RobotId = NewType("RobotId", str)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def new_correlation_id() -> CorrelationId:
    """Fresh correlation id for tracing a request across services."""
    return CorrelationId(_new_id("cor"))


def new_session_id() -> SessionId:
    """Fresh id for one continuous voice/interaction session."""
    return SessionId(_new_id("ses"))


def new_utterance_id() -> UtteranceId:
    """Fresh id for one utterance (a single ASR/TTS unit)."""
    return UtteranceId(_new_id("utt"))
