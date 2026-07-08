# humanoid-robot-adapters-audio-null

Runtime-null AudioInPort / AudioOutPort. Nothing fancy — the input yields
silence at the configured rate, and the output discards everything.

## When to use

- CI end-to-end tests that need real entry-point resolution without real
  audio hardware.
- The HITL voice smoke test on a robot without wired-up speakers/mics.
- Bring-up on new robots where the vendor audio drivers are not ready yet
  and you want to verify the software stack in isolation.

## Configuration

```yaml
stack:
  audio_in:
    name: null
    config:
      sample_rate_hz: 16000
      channels: 1
      frame_ms: 50
  audio_out:
    name: null
    config:
      # No config options today; a counter tracks bytes played.
      {}
```
