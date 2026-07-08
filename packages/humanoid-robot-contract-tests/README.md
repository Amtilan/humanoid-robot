# humanoid-robot-contract-tests

The **single source of truth** for what a robot adapter must guarantee.

Adapters plug in like this:

```python
# In an adapter's tests/test_contract.py:
from humanoid_robot.contract_tests import RobotAdapterContract
from humanoid_robot.testing import MockRobotAdapter

class TestMyAdapter(RobotAdapterContract):
    @pytest.fixture
    def adapter(self):
        return MockRobotAdapter()  # or your real adapter
```

That's it — pytest picks up every inherited test method.

## What the contract enforces

- `manifest` is a `RobotManifest` and does not change across `.start()/.stop()`.
- `capabilities == manifest.capabilities` (no drift).
- `start()` then `stop()` succeeds and is idempotent.
- Double `start()` is safe (idempotent).
- After `stop()`, calling `start()` again works.

Every new adapter — including the mock — is contract-tested in CI.
