"""Meta-test: our `MockRobotAdapter` passes the shared contract."""

from __future__ import annotations

import pytest

from humanoid_robot.contract_tests import RobotAdapterContract
from humanoid_robot.testing import MockRobotAdapter


class TestMockAgainstContract(RobotAdapterContract):
    @pytest.fixture
    def adapter(self) -> MockRobotAdapter:
        return MockRobotAdapter()
