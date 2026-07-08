"""Contract test suite for `RobotAdapterPort` implementations.

Adapter authors subclass `RobotAdapterContract` and provide the `adapter`
fixture. pytest inherits every method and runs them against the fixture.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable

import pytest

from humanoid_robot.domain.robot import RobotCapabilities, RobotManifest


@runtime_checkable
class _AdapterUnderTest(Protocol):
    """Minimal duck-type; RobotAdapterPort at runtime plus optional idempotency."""

    manifest: RobotManifest
    capabilities: RobotCapabilities

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class RobotAdapterContract:
    """Every `RobotAdapterPort` implementation must pass this suite."""

    @pytest.fixture
    @abstractmethod
    def adapter(self) -> _AdapterUnderTest:  # pragma: no cover — subclass provides
        raise NotImplementedError

    async def test_manifest_is_a_robot_manifest(self, adapter: _AdapterUnderTest) -> None:
        assert isinstance(adapter.manifest, RobotManifest)

    async def test_capabilities_match_manifest(self, adapter: _AdapterUnderTest) -> None:
        assert adapter.capabilities == adapter.manifest.capabilities

    async def test_start_then_stop_succeeds(self, adapter: _AdapterUnderTest) -> None:
        await adapter.start()
        await adapter.stop()

    async def test_start_is_idempotent(self, adapter: _AdapterUnderTest) -> None:
        await adapter.start()
        await adapter.start()  # must not raise
        await adapter.stop()

    async def test_restart_after_stop(self, adapter: _AdapterUnderTest) -> None:
        await adapter.start()
        await adapter.stop()
        await adapter.start()
        await adapter.stop()

    async def test_manifest_is_stable_across_lifecycle(self, adapter: _AdapterUnderTest) -> None:
        before = adapter.manifest
        await adapter.start()
        during = adapter.manifest
        await adapter.stop()
        after = adapter.manifest
        assert before == during == after
