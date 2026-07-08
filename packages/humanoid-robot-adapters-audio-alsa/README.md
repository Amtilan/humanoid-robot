# humanoid-robot-adapters-audio-alsa

`AudioInPort` on top of an `arecord` subprocess. Intended for developer
machines and robot builds without a hardware AEC mic array (see ADR-0004).
Production robots run the `humanoid-robot-adapters-unitree-g1` audio-in
path or a driver for their specific mic array.

## Configuration

```python
AlsaAudioIn(
    config=AlsaAudioInConfig(
        device="plughw:2,0",
        sample_rate_hz=16_000,
        channels=1,
        frame_ms=50,
    )
)
```

## System prerequisites

- `alsa-utils` installed (`arecord` on PATH).
- The user running `cortex-voice` is in the `audio` group.
