# HITL smoke test — full voice loop

Purpose: verify end-to-end that a running robot can (a) accept an
`LlmAnswer` event on NATS, (b) synthesize it with Piper, and (c) push the
audio to whatever `AudioOutPort` was wired up. The mic side is fed by a
null stream so the test does not depend on a wake-word firing.

The real listen path (mic → VAD → ASR → `asr.final`) is exercised in unit
tests already; here we validate the TTS/output half against the real
runtime dependencies.

## Prerequisites (on the robot)

- `nats-server` reachable at `HR_VOICE_NATS`.
- `humanoid-robot-adapters-asr-whisper[runtime]`,
  `humanoid-robot-adapters-tts-piper[runtime]`,
  `humanoid-robot-adapters-vad-silero[runtime]` installed.
- Piper voice `.onnx` file downloaded, exported as `HR_VOICE_PIPER_RU`.

## Run

```bash
export HR_VOICE_NATS=nats://127.0.0.1:4222
export HR_VOICE_PIPER_RU=/opt/piper/voices/ru_RU-ruslan-medium.onnx
uv run python scripts/hitl_voice_smoke.py
```

Expected: `hitl voice smoke: OK` and exit code 0 within ~30 s.

## Wiring real robot audio

Replace `_NullAudioIn` / `_NullAudioOut` in the script with:

- `_NullAudioIn` → an ALSA reader (`arecord` subprocess) or the G1 mic
  multicast client (Phase 2c will provide `UnitreeG1AudioIn`).
- `_NullAudioOut` → `humanoid_robot.adapters.unitree_g1.UnitreeG1AudioOut`
  when running on the G1.
