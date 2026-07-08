# humanoid-robot-adapters-asr-whisper

`AsrPort` implemented on top of `faster-whisper` (CTranslate2), running the
`large-v3-turbo` model at INT8 by default per ADR-0005.

## Modes

- **Batch** — `transcribe_batch(pcm, sample_rate_hz, language_hint)` runs one
  Whisper decode on the buffer. Latency = model_time for the whole clip.
- **Streaming** — `transcribe_stream(frames)` consumes a live `AudioFrame`
  iterator. Speech boundaries are inferred from `VadPort` upstream; this
  adapter buffers per-utterance, emits partial hypotheses on every
  `_PARTIAL_INTERVAL_MS`, and a final hypothesis when the caller signals end
  of stream by closing the iterator.

## Configuration

```python
FasterWhisperAsr(
    model_id="large-v3-turbo",
    compute_type="int8",              # int8 | int8_float16 | float16
    device="cuda",                    # cuda | cpu | auto
    default_language=Language.RU,
    beam_size=5,
    partial_interval_ms=300,
)
```

## Installation

The adapter package imports fine everywhere. To actually run inference:

```bash
uv add "humanoid-robot-adapters-asr-whisper[runtime]"
```

`faster-whisper` bundles the CTranslate2 runtime. Model weights are pulled
by Whisper's own cache (default `~/.cache/whisper`) or from the location
given by `WHISPER_CACHE_DIR`.
