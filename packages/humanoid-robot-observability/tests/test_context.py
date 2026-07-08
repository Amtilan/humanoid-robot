"""Tests for context propagation."""

from __future__ import annotations

from humanoid_robot.observability import (
    bind_correlation_id,
    clear_context,
    current_context,
)


class TestContext:
    def test_no_context_by_default(self) -> None:
        clear_context()
        assert current_context() == {}

    def test_bound_correlation_id_shows_up(self) -> None:
        bind_correlation_id("cor_abc")
        try:
            assert current_context() == {"correlation_id": "cor_abc"}
        finally:
            clear_context()
