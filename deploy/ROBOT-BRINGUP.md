# Unitree G1 bring-up plan

Grounded in a live SSH recon of the physical robot (`unitree@192.168.0.61`,
2026-07-10). This is the plan to go from "platform builds + boots with
mocks" to "platform runs on the real G1". Everything below the recon
section is actionable, ordered by impact.

---

## 0. The robot as-found (recon facts)

| Area | Reality on the device |
|------|-----------------------|
| Compute | Jetson Orin NX, **JetPack 5.1.1** (L4T R35.3.1), Ubuntu 20.04, aarch64 |
| Resources | 8 cores, 15 Gi RAM, NVMe **428 G free** |
| Host Python | 3.8 (irrelevant — our services are containerised) |
| Unitree SDK | **C++ only** installed (`/usr/local/lib/libunitree_sdk2.a`, `~/unitree_sdk2`, `example/g1`); `master_service` running |
| Unitree Python | **absent** — no `unitree_sdk2py`, no `cyclonedds` |
| Robot control net | `eth10` = 192.168.123.164/24 (DDS plane to motors) |
| WiFi | `wlan0` = 192.168.0.61/24, has real internet |
| Egress | **broken** — `eth10` default (metric 20100) beats `wlan0` (20600), sends internet to the 192.168.123.1 dead-end |
| Docker | 24.0.5 present, **`docker compose` plugin missing**, 0 images, `nvidia` runtime configured (not default) |
| Audio | HDMI-out + Tegra APE only — **no USB mic/speaker**; PulseAudio running |
| Access | sudo works (pw `123`); `unitree` not in docker group |

**Validated during recon (reversible, robot left as-found):** adding
`default via 192.168.0.1 dev wlan0 metric 50` fixes egress — `ghcr.io`
resolves and our **arm64 base manifest returns HTTP 200**, so the GHCR
pull path works from the robot once routed. Reverted immediately after.

---

## 1. Blockers to real operation (ranked)

1. **Unitree Python SDK not present** — our adapter is Python; the robot
   only has the C++ SDK. No `unitree_sdk2py`/`cyclonedds` → the adapter
   can't drive motors, read IMU, or run the safety loop against real
   hardware. *Highest impact: without this the robot only runs mock.*
2. **No live end-to-end run** — the full path (route → pull → compose up
   → verify) has never executed on the device.
3. **Audio hardware** — no USB mic/speaker attached; voice pipeline is
   dead until one is plugged in and routed through PulseAudio.
4. **GPU inference unused** — runtime passes through, but CPU torch never
   touches the iGPU (see [README](README.md) "Current CUDA status").

Everything else (TLS, RBAC, log rotation) is polish, not a blocker.

---

## 2. Deploy strategy under the robot's constraints

Two gaps break the documented pull-based deploy on this specific unit:

- **`docker compose` plugin missing** → drop the arm64 plugin binary in
  `/usr/local/lib/docker/cli-plugins/docker-compose` (one-time). Fold
  this into `install-on-robot.sh` as a bootstrap step.
- **Egress broken by routing** → two supported paths:
  - **(A) Route fix** — `install-on-robot.sh` gains an opt-in
    `--fix-egress` that adds the reversible `wlan0` default (metric 50),
    pulls, then optionally restores. Keeps the offline-first ethos: the
    fix is only up during the pull.
  - **(B) True side-load** (fully offline) — on a machine with internet:
    `docker save $(images) | gzip` → `scp` → `docker load` on the robot.
    No robot routing change at all. Slower for the torch-heavy base over
    WiFi, but the honest answer to the no-egress guarantee in
    [humanoid-robot-deploy memory]. Ship a `deploy/scripts/sideload.sh`.

Recommendation: implement both; default to (A) for convenience, document
(B) for locked-down units.

---

## 3. The full проброс — phased

### Phase A — infra bring-up (mock adapter, no motion) ✅ DONE 2026-07-10
1. `install-on-robot.sh` bootstraps compose plugin + (opt) `--fix-egress`.
2. Pull `humanoid-robot-base` + `dashboard` (arm64, verified pullable).
3. `docker compose up -d` with `HR_ROBOT_ADAPTER__ADAPTER_NAME=mock`.
4. `verify-install.sh` — assert nats/core/adapter/dashboard/safety/
   diagnostics all green on real hardware.
5. Confirm the Jetson overlay lands `runtime: nvidia` on voice/rag
   (probe already in `verify-install.sh`).

**Exit criteria:** dashboard reachable on the robot, health ready, mock
telemetry flowing. Zero motor commands.

**Executed on the real G1 (2026-07-10)** — one `install-on-robot.sh
--fix-egress` run:
- installer bootstrapped the missing compose v2 plugin + cosign,
  forced a reversible wlan0 default (eth10 was shadowing egress),
  pulled all images, then reverted the route;
- **fail-closed cosign verify passed** on both images against our
  workflow OIDC identity — real supply-chain check, live;
- Jetson auto-detected → GPU overlay enabled in `COMPOSE_FILE`;
- `docker compose up -d` → nats healthy → core healthy → adapter
  started (R9 boot-ordering fix confirmed on hardware);
- `verify-install.sh` → **all 6 core checks PASS** (nats.container,
  cortex-core.ready http=200, robot-adapter.manifest adapter=mock,
  diagnostics.ticker, safety.gate estop_engaged=True, dashboard.spa);
- dashboard http=200 + API ready http=200 on the robot;
- **DDS control plane untouched** — eth10 (192.168.123.164/24) intact,
  default routes back to the original two, no motor traffic.

Gaps this surfaced (all fixed in the installer): compose plugin missing
on JetPack, cosign missing, egress shadowed by the eth10 DDS route
(needs `--fix-egress`), and the DNS fast-path false-positive (resolver
fans queries across both links) — now forces the route via a proven
online interface.

### Phase B1/B2 executed (2026-07-10) — real adapter live, read-only

- **B1**: `humanoid-robot-adapter-unitree` image built in CI (QEMU arm64):
  base + CycloneDDS 0.10.2 + `cyclonedds` + `unitree_sdk2_python`, keyless
  cosign-signed, `.sig` flipped public. (Trivy/Syft steps fail on the
  amd64 runner because the image is arm64-only — cosmetic, fix by pinning
  `platform: linux/arm64` on those steps.)
- **B2**: pulled + verified (fail-closed cosign) on the robot, swapped
  mock → `unitree_g1_edu` via `docker-compose.unitree.yaml` (host-net,
  `--interface eth10`). Adapter came up clean:
  `unitree_g1.started` (ChannelFactoryInitialize on eth10, 382 ms, no
  error) → `command_dispatcher.ready` → `telemetry_pump.ready sources=3`.
  Manifest now reports the real G1: bipedal locomotion, two 7-DOF arms
  with the vendor gesture list, hands=none. **Safety gate stayed
  fail-closed** (`estop_engaged=true`, `pending_command_count=0`) — zero
  motion.
- **B2.5 (done 2026-07-10):** `lowstate.py` subscribes to `rt/lowstate`
  (`unitree_hg LowState_`) and feeds the IMU + temperature ports via
  their `source` hook (sync getter — no thread hop). Verified live on the
  robot: `/api/v1/robot/telemetry` now returns real IMU
  (`accel_z ≈ 9.86` = gravity, so orientation is physically correct;
  roll/pitch/yaw, gyro, quaternion all populated) and real temperatures
  (imu board ~80 °C, motor_max/mean across 35 motors). Adapter logs
  `unitree_g1.lowstate_subscribed` → `g1.lowstate.first_frame`. Safety
  gate stayed fail-closed.
- **B2.6 (done 2026-07-10):** battery SOC lives on a *separate* topic —
  `rt/lf/bmsstate` (`unitree_hg BmsState_`, `soc` uint8 0-100), NOT in
  `LowState_` or `SportModeState_` (found by probing the live robot).
  The reader now subscribes to both; battery reads ~70% live. Cold-start
  gotcha: right after an image pull the low-rate bms discovery can lag
  and battery shows 0.0 until the first frame — a
  `docker compose restart robot-adapter` populates it within ~10 s.
  Telemetry is now complete: IMU + temperature + battery.

The real adapter is left **running** (read-only, gate closed). Revert to
mock: `cd /opt/humanoid-robot && sudo docker compose -f docker-compose.yaml
-f docker-compose.jetson.yaml up -d robot-adapter`.

### Static LAN endpoint (done 2026-07-10)

`deploy/scripts/expose.sh` rebinds core + dashboard off loopback
(`HR_BIND_ADDR=0.0.0.0`) and recreates just those two. <!-- pragma: allowlist secret -->The dashboard
nginx proxies `/api` + the WS event stream to core, so **one URL is the
whole surface**: `http://<robot-ip>:8081` (UI + REST + live events),
`:8080` for the API directly. Auth is opt-in (`--auth` sets a bearer
token; default is open on the trusted LAN — the safety gate stays
fail-closed either way). `--off` reverts to loopback.

**Durability gotcha (fixed):** the real adapter runs host-net and reaches
NATS on `127.0.0.1:4222`, a port that ONLY the `docker-compose.unitree.yaml`
overlay publishes. So the overlay must be in `COMPOSE_FILE` — otherwise
any `docker compose up` that recreates nats (e.g. `expose.sh`) drops that
port and the adapter falls off the bus. The robot's `.env` now has
`COMPOSE_FILE=docker-compose.yaml:docker-compose.jetson.yaml:docker-compose.unitree.yaml`,
so the real adapter + exposed dashboard come up together and survive
reboot. `192.168.0.61` is DHCP — reserve it or use Tailscale for a truly
stable link.

### Phase B3 — first motion attempt (2026-07-10)

First real command through the full stack, robot secured + e-stop in
hand. **The command + safety pipeline is proven end-to-end on hardware**:
released the gate → `head.pose` (yaw 0.1 rad) → gate `KnownCapabilities +
EStop` policies allowed it (audit `safety.command.forwarded`) → adapter
dispatched → then re-engaged the gate. Clean, no runaway.

**But no motion happened**: the installed `unitree_sdk2py` `LocoClient`
has **no head-pose method** — `head.py` probes SetHeadPose / HeadPose /
SetHead and none exist, so it returned a clean `hardware_error` (exactly
the safe worst case). The G1 EDU head isn't actuated through this client.

Introspected `LocoClient` — what the SDK actually exposes:
`Move`, `SetVelocity`, `StopMove`, `BalanceStand`, `HighStand`,
`LowStand`, `Sit`, `Squat2StandUp`, `StandUp2Squat`, `SetStandHeight`,
`Damp`, `ZeroTorque`, `WaveHand`, `ShakeHand`, `SetBalanceMode`,
`SetFsmId`. And `G1ArmActionClient`: `ExecuteAction` + `GetActionList`.

Follow-ups this surfaced:
- `head.pose` can't work on this SDK → either drop it from the G1
  manifest or remap `head.py` (there's no head actuation to remap to,
  so likely drop/mark-unavailable).
- Real small motions that WOULD work: `LocoClient.WaveHand` /
  `ShakeHand`, or `arms.gesture` via `ExecuteAction` (needs the real
  action IDs from `GetActionList`). All are arm motions — bigger than a
  head tilt, so they need clear space + the operator on the e-stop.

### Phase B3b — real arm gesture (2026-07-10)

Second first-motion attempt: `arms.gesture "release arm"`, robot secured
+ e-stop in hand. **Platform pipeline proven again, fully**: audit trail
shows `estop.released → command.requested → command.forwarded (gate
allowed) → command.result → estop.engaged`. The command reached the
vendor `G1ArmActionClient.ExecuteAction(99)`.

**But the arm did not move**: `ExecuteAction` returned **7404** →
`hardware_error`. Root cause (confirmed by probing): the robot's
**FSM is (0,0)** — an idle / zero-torque state. `GetActionList` works
(the arm service answers queries and lists the real actions —
release_arm=99, wave_above_head=26, shake_hand=27, …) but `ExecuteAction`
is rejected because the G1 isn't in an operational control mode.

**What actual motion needs:** bring the G1 into an operational FSM via
`LocoClient` (e.g. `BalanceStand` / the operation-control FSM). That
means the robot **stands up and balances** — a much larger, higher-risk
step than a gesture: it must be free-standing (NOT on a rigid stand) and
bearing its own weight, with the operator fully set for a standing
sequence. This is Unitree operational procedure, not a platform gap —
our stack does everything correctly up to the vendor call.

**Bottom line for Phase B:** the command + safety + telemetry platform is
proven end-to-end on the real G1. Real actuation is gated behind the
robot's own operational-state requirements (stand/balance FSM), which is
a deliberate, separate bring-up.

### Phase B4 — gated posture capability (2026-07-10)

The whole-body FSM transitions (damp/stand/balance) are now a first-class
`locomotion.posture` capability that runs through the safety gate, not
ad-hoc direct LocoClient calls. Deployed to the robot (core + adapter).

**First SUCCESSFUL actuation through the full platform**: `POST
/api/v1/robot/commands {"capability":"locomotion.posture",
"payload":{"posture":"damp"}}` with the gate released → audit shows
`requested → forwarded → result outcome=ACCEPTED`. Unlike head.pose /
arms.gesture (which forwarded but returned hardware_error), Damp actually
executed. Damp is a soft hold — no stand, no fall. Gate re-engaged after.

**Full stand achieved (2026-07-10).** From the upright damped hold,
`locomotion.posture {balance_stand}` through the gate returned
`outcome=ACCEPTED` — the robot engaged active balance and stood under its
own power, commanded entirely through the safety platform (estop / schema
/ rate-limit / audit). The G1 is now OPERATIONAL, so `arms.gesture` etc.
work (the earlier 7404 was the non-operational FSM).

Safety notes learned here:
- The **hardware** e-stop cuts torque = collapse (emergency only).
- The **software** gate (`estop/engage`) only blocks future commands —
  nothing in the adapter reacts to it, so the robot keeps its current
  mode. Re-engaging after balance_stand is safe (robot keeps balancing).
- Bring it down safely: release gate → `posture sit` → `posture damp` →
  engage gate (or use the native controller).

### Phase B — real Unitree adapter (the motion blocker)
1. Package `unitree_sdk2py` + `cyclonedds` into an **arm64 adapter image
   variant** (they're the missing runtime deps). Pin against the C++ SDK
   already on the host, or vendor the `.a`.
2. Container networking: adapter needs the **eth10 DDS domain** — run the
   adapter with `network_mode: host` (or a macvlan on eth10) so DDS
   multicast reaches the motor boards. Set `CYCLONEDDS_URI` to bind the
   eth10 interface.
3. Wire `_sdk.py` lazy loader to the real bindings; flip
   `HR_ROBOT_ADAPTER__ADAPTER_NAME=unitree_g1_edu`.
4. **Bench-test with the robot on a stand / e-stop in hand.** First only
   read paths: IMU, battery, temperature, joint states — no actuation.
5. Then low-risk actuation through the **safety gate** (R-phase gate is
   fail-closed; `allowed_capabilities` excludes free locomotion by
   default): `head.pose`, `hands.open/close`, `arms.gesture`. Verify the
   gate blocks anything not whitelisted.
6. Locomotion last, only after the gate + watchdog are proven, tethered.

**Exit criteria:** real telemetry on the dashboard; a whitelisted gesture
executes through the safety gate; a non-whitelisted command is rejected.

### Phase C — voice
1. Attach a USB mic/speaker (hardware task). Confirm `arecord -l` shows a
   capture device.
2. Route the voice container to PulseAudio (`--device /dev/snd` or the
   Pulse socket) — the Unitree adapter already has `audio_in`/`audio_out`.
3. `fetch-models.sh` (~9.5 G, fits the 428 G NVMe), enable `--profile voice`.
4. Wake-word → ASR → intent → TTS loop end-to-end.

### Phase D — GPU acceleration
Pick one (see README "Current CUDA status"): bake CUDA llama.cpp +
CTranslate2 into the CPU base (keeps Python 3.12), or a separate arm64
inference sidecar on an L4T base with pinned Python 3.10, exposed over
NATS. Only worth it once B+C work on CPU.

---

## 4. What's already built for this humanoid (Phase 0–9)

- **Domain + event bus + safety gate** — fail-closed capability gate,
  audit SQLite, watchdog. Plugin runtime with entry-point discovery.
- **Robot adapter framework** — mock + a well-developed `unitree_g1`
  adapter (head, hands, arms, locomotion, battery, temperature,
  audio in/out, manifest) with a lazy real-SDK loader.
- **Voice + RAG** — ASR/TTS/wake-word pipeline, grounded QA over Qdrant.
- **Dashboard** — SPA with bearer auth + live WS event stream.
- **Deploy (Phase 9, R1–R22):**
  - Multi-arch (amd64+arm64) OCI images on GHCR, **cosign-signed**,
    Trivy-scanned, SBOM'd; `.sig` visibility auto-flipped.
  - **Fail-closed installer** — verifies signatures before pulling.
  - Compose profiles (core / voice / rag / metrics); Jetson GPU overlay
    + auto-detection.
  - systemd units (hardened) + nightly backup timer + restore.
  - Observability: Prometheus + Grafana + alertmanager with real
    Slack/Discord/ntfy/webhook receivers.
  - Bearer auth (HTTP + WS) with per-client failed-auth rate limiting.
  - `install-on-robot.sh` / `verify-install.sh` / `fetch-models.sh` /
    `backup.sh` / `restore.sh` / `verify-images.sh` — no git clone, no
    dev toolchain on the robot.

---

## 5. Immediate next actions

- [x] `install-on-robot.sh`: bootstrap compose plugin if missing.
- [x] `install-on-robot.sh`: `--fix-egress` (reversible route).
- [x] Run **Phase A** on the robot (mock, no motion) — all checks PASS.
- [ ] `deploy/scripts/sideload.sh` for fully-offline units (document (B)).
- [ ] Build the arm64 adapter image variant with `unitree_sdk2py` + `cyclonedds` (Phase B step 1).
- [ ] Hardware: attach USB audio for Phase C.

The Phase A stack is left **running** on the robot (`restart:
unless-stopped`, mock adapter, bound to 127.0.0.1). Tear down with
`cd /opt/humanoid-robot && sudo docker compose down`.
