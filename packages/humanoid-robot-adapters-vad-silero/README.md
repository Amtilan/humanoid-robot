# humanoid-robot-adapters-vad-silero

`VadPort` on top of Silero VAD v5 (ONNX).

- Frame size: 512 samples @ 16 kHz (32 ms), which is the model's native
  frame. The adapter buffers input to this size — callers can push frames
  of any length.
- Threshold: `speech_probability >= threshold` → `is_speech=True`. Default
  0.5, adjustable in config.

## Installation

Package imports fine everywhere. Enable runtime dependencies with:

```bash
uv add "humanoid-robot-adapters-vad-silero[runtime]"
```
