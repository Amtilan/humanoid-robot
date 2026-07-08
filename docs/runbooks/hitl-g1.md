# HITL smoke test — Unitree G1

Purpose: verify the `unitree_g1_edu` adapter against a physical G1 without
running the full cortex-core stack. Establishes the shortest possible path
between "we changed the adapter" and "the robot acknowledges it".

## Prerequisites (on the robot)

- `unitree_sdk2py` importable (see the vendor install instructions).
- `nats-server` reachable at `HR_G1_NATS` (default `nats://127.0.0.1:4222`).
  During development you can run it in Docker via
  `deploy/docker/nats.compose.yaml`.
- The DDS network interface (typically `eth10`) is up and reachable to the
  robot MCU (usually `192.168.123.161`).

## Run

```bash
cd /opt/humanoid-robot                       # or wherever the release lives
export HR_G1_INTERFACE=eth10
export HR_G1_MIC_SOURCE=g1
export HR_G1_NATS=nats://127.0.0.1:4222
uv run python scripts/hitl_g1_smoke.py
```

Expected output:

- The manifest as JSON.
- `published RobotAdapterReady on nats://…` followed by a clean exit.

## Debugging

- `nats sub 'robot.adapter.>'` in another terminal will show the manifest as
  it hits the bus.
- Missing SDK → `UnitreeSdkNotAvailableError` with an install pointer.
- DDS channel init hanging: check `ip -br addr` — the target interface must
  be up with a `192.168.123.0/24` address.

## What this smoke test does NOT do (yet)

- Send actual motion commands (locomotion / arms). That is Phase 2b.
- Stream audio. That is Phase 3.

Both are called out in the Phase 2 exit criteria and will be added in
subsequent PRs, with `pytest.mark.hardware` integration tests running
against them.
