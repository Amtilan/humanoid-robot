"""Shared kernel tests."""

from __future__ import annotations

import re
from datetime import UTC

from humanoid_robot.domain.shared import (
    new_correlation_id,
    new_session_id,
    new_utterance_id,
    utc_now,
)

_HEX_RE = re.compile(r"^[a-z]{3}_[0-9a-f]{32}$")


class TestIdentifiers:
    def test_correlation_id_has_prefix_and_hex(self) -> None:
        value = new_correlation_id()
        assert _HEX_RE.match(value), value

    def test_session_id_has_prefix_and_hex(self) -> None:
        value = new_session_id()
        assert _HEX_RE.match(value), value

    def test_utterance_id_has_prefix_and_hex(self) -> None:
        value = new_utterance_id()
        assert _HEX_RE.match(value), value

    def test_ids_are_unique_across_calls(self) -> None:
        ids = {new_correlation_id() for _ in range(1000)}
        assert len(ids) == 1000


class TestTimestamps:
    def test_utc_now_is_timezone_aware(self) -> None:
        now = utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset() == UTC.utcoffset(now)
