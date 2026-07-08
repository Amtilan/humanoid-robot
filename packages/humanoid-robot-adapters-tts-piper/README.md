# humanoid-robot-adapters-tts-piper

`TtsPort` on top of Piper (ONNX). Ships one adapter that can host multiple
voices — one voice per language, resolved from `TtsRequest.language` and
`TtsRequest.voice_id`.

## Configuration

```python
PiperTts(
    config=PiperConfig(
        voice_paths={
            "ru": "/opt/piper/voices/ru_RU-ruslan-medium.onnx",
            "en": "/opt/piper/voices/en_US-lessac-medium.onnx",
        },
        default_language=Language.RU,
    )
)
```

## Installation

Package imports fine everywhere. To actually synthesize:

```bash
uv add "humanoid-robot-adapters-tts-piper[runtime]"
```

Piper voices are `.onnx` files paired with `.onnx.json` metadata. Download
from https://huggingface.co/rhasspy/piper-voices .
