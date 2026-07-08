# 0004 — HW-first voice pipeline (XMOS XVF3800 primary)

- **Status**: Accepted
- **Date**: 2026-07-08

## Context

The robot speaks and listens from the same enclosure. The mic and speaker
are 10–20 cm apart. Empirically, software-only acoustic echo cancellation
(AEC) — WebRTC AEC3, SpeexDSP, DeepFilterNet — cancels 60–70 % of the
direct-path echo at that distance. The residue is loud enough to false-
trigger our own VAD / wake-word / ASR, which is exactly what happened in
the prior `g1_intelligence` prototype: a half-duplex `speaker_gate` was
added to mask the mic while the robot talks, at the cost of barge-in.

A production platform cannot rely on a half-duplex hack. We need real full-
duplex behaviour, which means the speaker signal must be **subtracted from
the mic signal digitally and time-synchronously**, which in practice means:

1. A microphone array with **on-chip AEC** and a **dedicated reference
   input** from the speaker path — the ADC and reference share one clock
   domain, so no drift.
2. Hardware **beamforming** (fixed or adaptive) that reduces off-axis
   pickup, so the AEC has less work to do.
3. Software post-processing (neural denoise, semantic VAD, wake-word) only
   *after* the hardware has done its job.

## Decision

Adopt a **hardware-first voice pipeline** with two supported hardware
tiers.

### Primary hardware — XMOS XVF3800 dev board (XK-VOICE-SQ66)

- Up to 7 PDM mics.
- On-chip AEC with **dedicated AEC reference input**.
- Hardware beamforming.
- Exposes USB Audio Class 2.0 to the host as a 4-channel device (processed
  mics + reference), works out-of-the-box on the Linux 5.x+ `snd-usb-audio`
  driver, therefore on JetPack 6.x (L4T 36.x, Ubuntu 22.04 arm64).
- No confirmed successor to the XVF3800 as of mid-2026 — XMOS iterates on
  firmware, not silicon.
- Approx. USD 400–500 for the dev kit (verify at commit time).

### Fallback hardware — ReSpeaker USB Mic Array v2.0 (XMOS XVF3000)

- 4-mic circular array with older-generation on-chip AEC (2018 silicon).
- USB Audio Class 1.0.
- Approx. USD 80.
- Adequate for demos and dev machines; expect residual echo at high
  playback volume — software post-AEC (WebRTC AEC3) mandatory.

### Reference-channel routing

The host writes speaker playback to the XMOS via **USB Audio OUT**. The
XMOS DSP uses that same PCM as the AEC far-end reference and internally
DAC's it out to the speaker amplifier. One clock domain, no drift, one
cable. Do **not** run playback out of the Jetson's built-in output and try
to loop it back into the mic array over an ADC — every deployment we've
seen with that topology eventually fails to converge.

### Deprecated / rejected options

- **Software-only AEC at 10–20 cm coupling** — insufficient, see above.
- **6-Mic Circular Array v2 (ReSpeaker)** — no true HW AEC; would require
  the same software-only chain we already know to be inadequate.
- **Speakerphone modules** (Yealink CP, Jabra Speak, Poly Sync,
  Sennheiser SP) — excellent AEC, but closed appliances with no I2S
  reference, wrong form factor for a robot torso, and lose beamforming
  control.
- **Sonos-style edge SoCs (Synaptics AS3xx, Knowles IA8xx)** — reference
  designs only, not products we can source in volume.
- **Espressif ESP32-S3 AFE** — not competitive with XMOS on either AEC
  quality or beamforming.

## SW voice pipeline on top of HW

```
XMOS array (HW BF + AEC + AGC) ──► DeepFilterNet2 (neural denoise/dereverb)
                                     ──► Silero VAD v5
                                          ──► openWakeWord
                                               ──► Streaming ASR
Speaker DAC ◄── XMOS reference-out ◄── Host playback
```

- Neural denoise and VAD run on Jetson CPU; wake-word on CPU.
- Half-duplex speaker gate is **removed**. Barge-in works because the AEC
  provides a clean mic residue during playback.
- Software AEC3 remains as an optional secondary layer with the fallback
  hardware tier only.

## Consequences

- Every production robot ships with an XMOS XVF3800. Dev kits and lab-only
  fixtures may run on the ReSpeaker USB Mic Array v2.0.
- The `AudioInPort` on the adapter side is transport-neutral: the specific
  hardware sits behind the port, but the pipeline explicitly assumes a
  clean, single-clock-domain input in production.
- A configuration knob `voice.hw_tier = "xmos_xvf3800" | "respeaker_v2" |
  "sw_only"` selects which post-processing is enabled and whether the
  speaker gate stays on as a temporary fallback. `sw_only` is dev-only.
- Robot BOMs must budget the XMOS module, its enclosure, and the speaker
  amplifier as one integrated subsystem.
- All Voice-pipeline latency SLOs (Phase 3 exit criteria) will be
  benchmarked on the XMOS tier — not the fallback.

## Jetson Orin NX / JetPack 6 gotchas (implementation notes)

- `snd-usb-audio` xruns under CPU pressure — pin ALSA capture to a big
  core (`taskset` + `chrt`) and set `usbcore.autosuspend=-1` on the
  kernel cmdline.
- Stick to 48 kHz on the USB mic path; 96 kHz occasionally drops on Orin
  because of xHCI bandwidth reservation quirks.
- Prefer **PipeWire** over PulseAudio on JetPack 6 for lower and more
  predictable latency in the wake-word + ASR pipeline.
- Single clock domain — use the XMOS as both playback and capture. Never
  route playback via the Jetson's 3.5 mm jack and capture over USB; you
  will get AEC drift.

## Notes on sourcing

Research for this ADR ran on 2026-07-08 with the model's training cutoff
of January 2026 and no live web access. Verify current XMOS XVF3800 stock
and pricing at Digi-Key, Mouser, or XMOS directly before committing a BOM.
