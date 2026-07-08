# humanoid-robot-adapters-wakeword-openwakeword

`WakeWordPort` on top of openWakeWord (ONNX). Ships one detector that can
be pointed at any of the ONNX wake-word models under the openWakeWord
repository or trained from your own audio.

## Configuration

```python
OpenWakeWord(
    config=OpenWakeWordConfig(
        model_paths=["/opt/wake_words/hey_robot.onnx"],
        threshold=0.5,
    )
)
```

The adapter buffers 16 kHz mono PCM16 into the detector's native window
size (openWakeWord uses 1280-sample frames = 80 ms at 16 kHz).

## Installation

The `[runtime]` extra installs `onnxruntime` + `numpy`. The `openwakeword`
package itself is not on PyPI with Python 3.12 wheels for `tflite-runtime`,
so install it manually with the ONNX-only path:

```bash
uv add "humanoid-robot-adapters-wakeword-openwakeword[runtime]"
uv pip install --no-deps openwakeword
```

The adapter only uses openWakeWord's ONNX inference framework, so
tflite-runtime is not needed at execution time.
