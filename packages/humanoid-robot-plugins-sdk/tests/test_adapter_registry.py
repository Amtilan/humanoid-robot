"""AdapterRegistry tests using an in-process factory (no importlib.metadata)."""

from __future__ import annotations

import pytest

from humanoid_robot.plugins_sdk import (
    AdapterEntry,
    AdapterRegistry,
    UnknownAdapterError,
)
from humanoid_robot.testing import MockRobotAdapter


def _mock_factory(**_: object) -> MockRobotAdapter:
    return MockRobotAdapter()


class TestAdapterRegistry:
    def test_from_entries_lists_names_sorted(self) -> None:
        reg = AdapterRegistry.from_entries(
            [
                AdapterEntry(name="b", factory=_mock_factory, distribution=None, version=None),
                AdapterEntry(name="a", factory=_mock_factory, distribution=None, version=None),
            ]
        )
        assert reg.names() == ("a", "b")

    def test_build_returns_adapter_instance(self) -> None:
        reg = AdapterRegistry.from_entries(
            [AdapterEntry(name="mock", factory=_mock_factory, distribution=None, version=None)]
        )
        adapter = reg.build("mock")
        assert isinstance(adapter, MockRobotAdapter)

    def test_missing_name_raises_with_available_list(self) -> None:
        reg = AdapterRegistry.from_entries(
            [AdapterEntry(name="mock", factory=_mock_factory, distribution=None, version=None)]
        )
        with pytest.raises(UnknownAdapterError, match="available: mock"):
            reg.build("nope")

    def test_discover_returns_registry(self) -> None:
        # We rely on `discover` not crashing on empty groups; adapters
        # register themselves via their own pyproject entry points and
        # will show up in integration environments.
        reg = AdapterRegistry.discover(group="humanoid_robot.tests.__no_such_group__")
        assert reg.names() == ()
