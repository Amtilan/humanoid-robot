# cortex-voice

Orchestrates the voice pipeline. Owns one `VoiceSession` at a time:

```
AudioInPort  ──► VadPort ──► [buffer]  ──► AsrPort  ──► NATS (asr.final)
                              │                                 │
                              ▼                                 ▼
                        SpeechDetected                       LlmAnswer  (Phase 4)
                                                                │
                                                                ▼
                                                          TtsPort ──► AudioOutPort
```

At Phase 3 round 1, only the top row is implemented. The bottom row (LLM
response → TTS → speaker) is stubbed for testing and will be enabled once
Phase 4 lands.

Ports are injected — `cortex-voice` doesn't import faster-whisper, piper,
or silero directly. That means the orchestrator can be exercised in unit
tests with in-memory fakes.
