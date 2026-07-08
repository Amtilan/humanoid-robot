"""UTC-only timestamps.

We forbid naive datetimes in the domain — every timestamp is timezone-aware.
Serialising via ISO-8601 keeps event schemas language-agnostic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime

Timestamp = Annotated[datetime, AwareDatetime]


def utc_now() -> datetime:
    """Current time, timezone-aware UTC."""
    return datetime.now(tz=UTC)
