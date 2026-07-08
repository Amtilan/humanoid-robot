# humanoid-robot-adapters-unitree-g1

Adapter for the **Unitree G1 Edu** humanoid.

## Runtime requirements

- `unitree_sdk2_python` importable at runtime (vendor-shipped, not on PyPI).
  Install on the robot per [Unitree docs](https://github.com/unitreerobotics/unitree_sdk2_python).
- CycloneDDS bindings (`libddsc-dev` at the OS level; the Python SDK bundles
  its side).
- The Ethernet interface talking to the robot MCU — defaults to `eth0`,
  overridden through the adapter kwargs / manifest (typical G1 stack:
  `eth10`).

The package **does not** require the SDK to import. Imports are deferred
until `start()`, so tests, packaging, and dev-laptop workflows work
everywhere. Attempting to `start()` without the SDK raises
`UnitreeSdkNotAvailableError` with a clear remediation.

## Registration

Auto-registered under the `humanoid_robot.robot_adapters` entry-point group
as `unitree_g1_edu`.

## Kwargs

```python
UnitreeG1Adapter(
    network_interface="eth10",
    mic_source="g1",                 # "g1" | "alsa" | "r1"
    mic_alsa_device="plughw:2,0",    # only when mic_source="alsa"
    speaker_volume=100,              # 0..100
)
```

Everything else lives in the published `RobotManifest`.
