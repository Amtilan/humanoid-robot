"""Hardware-in-the-loop smoke test against a live Unitree G1.

Runs on the robot (or with SSH tunnel-forwarded network access to it).
Do NOT run this on developer laptops — it will attempt to import the Unitree
Python SDK and open a DDS channel on the configured interface.

Usage
-----
    HR_G1_INTERFACE=eth10 python scripts/hitl_g1_smoke.py

The script:
  1. Builds the manifest and prints it.
  2. Starts the adapter (opens DDS ChannelFactory).
  3. Publishes RobotAdapterReady into NATS at HR_G1_NATS
     (default: nats://127.0.0.1:4222 — must be running on the robot).
  4. Sleeps 3 seconds so a subscriber can see the event.
  5. Cleanly stops the adapter.

Exit code: 0 on success, non-zero on any error.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.adapters.unitree_g1 import UnitreeG1Adapter, UnitreeG1Settings
from humanoid_robot.domain.shared import new_correlation_id
from humanoid_robot.events import RobotAdapterReady
from humanoid_robot.events.base import EventMetadata


async def _main() -> int:
    interface = os.environ.get("HR_G1_INTERFACE", "eth10")
    mic_source = os.environ.get("HR_G1_MIC_SOURCE", "g1")
    nats_url = os.environ.get("HR_G1_NATS", "nats://127.0.0.1:4222")

    settings = UnitreeG1Settings(network_interface=interface, mic_source=mic_source)
    adapter = UnitreeG1Adapter.from_settings(settings)

    print("== manifest ==")
    print(json.dumps(adapter.manifest.model_dump(mode="json"), indent=2, ensure_ascii=False))

    bus = NatsEventBus(config=NatsEventBusConfig(servers=(nats_url,), name="hitl_smoke"))
    await bus.connect()
    try:
        await adapter.start()
        try:
            await bus.publish(
                RobotAdapterReady(
                    meta=EventMetadata(
                        correlation_id=new_correlation_id(),
                        producer="hitl-smoke",
                    ),
                    adapter_name=adapter.manifest.adapter_name,
                    adapter_version=adapter.manifest.adapter_version,
                    robot_model=adapter.manifest.robot_model,
                    capabilities=adapter.capabilities,
                )
            )
            print(f"published RobotAdapterReady on {nats_url}")
            await asyncio.sleep(3.0)
        finally:
            await adapter.stop()
    finally:
        await bus.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except Exception as exc:  # noqa: BLE001
        print(f"hitl smoke failed: {exc}", file=sys.stderr)
        sys.exit(1)
