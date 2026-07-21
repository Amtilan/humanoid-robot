# cortex-presence

Camera-based visitor detection for the presenter robot (plan stage 6).

Polls the camera bridge's JPEG snapshot endpoint (`camera_mjpeg`, :8091),
scores each frame with a motion detector (frame differencing — the exhibition
scene is static until someone walks up), and publishes a single
`visitor.detected` event per visit: the detector re-arms only after the scene
has been quiet for a while, so one visitor does not produce a greeting burst.

The greeting itself lives in cortex-rag (presenter mode): it voices the
approved welcome line with its own cooldown as a second anti-repeat guard.

```bash
cortex-presence --snapshot-url http://host.docker.internal:8091/camera/front/snapshot
```

Env overrides: `HR_PRESENCE_SNAPSHOT_URL`, `HR_PRESENCE_NATS_URL`.
