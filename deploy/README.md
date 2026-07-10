# Deployment

Two supported install paths:

- **Robot side** — no source, no build tools. Pull prebuilt OCI images
  from GHCR, one compose file, `docker compose up`. See
  [Robot-side install (no git clone)](#robot-side-install-no-git-clone).
- **Developer laptop / CI** — source-built compose stack for iterating
  on the platform. See [Local dev compose stack](#local-compose-stack).

The robot must **never** need to `git clone` this repo or run
`uv sync`. Every deployment round preserves both paths side-by-side.

## Robot-side install (no git clone)

```bash
curl -sSL https://raw.githubusercontent.com/Amtilan/humanoid-robot/main/deploy/scripts/install-on-robot.sh | sudo bash
cd /opt/humanoid-robot
docker compose up -d
```

That's it. The installer:

- fetches `docker-compose.yaml` + `nats.conf` into `/opt/humanoid-robot`
- fetches the reference env-files into `/etc/humanoid-robot/` (never
  overwrites existing ones)
- writes `/opt/humanoid-robot/.env` with `IMAGE_TAG`, `IMAGE_REGISTRY`,
  and `HR_ROBOT_ADAPTER__ADAPTER_NAME=mock` — override before `up`
- runs `docker compose pull` against `ghcr.io/amtilan/humanoid-robot-*`

Pin a specific release in production:

```bash
curl -sSL … | sudo IMAGE_TAG=v1.0.0 bash
```

### Verifying the install

`install-on-robot.sh` copies `verify-install.sh` alongside the compose
file. Run it after `docker compose up` for a robot-side smoke check —
same probes the CI `compose-smoke` workflow runs, but locally:

```bash
bash /opt/humanoid-robot/verify-install.sh
# extend the checks for opt-in profiles:
bash /opt/humanoid-robot/verify-install.sh --with voice --with rag --with metrics
```

Every check reports `PASS` / `FAIL` / `skip` in a summary table.
Exit code is 0 iff every non-skip check passed.

### Voice + RAG (opt-in, ~9.5 GB of models)

The base install runs cortex-core + robot-adapter + dashboard only —
those services fit in a few hundred MB and boot in seconds.  Voice
(ASR/TTS) and RAG (grounded QA) need model weights that don't belong
in an OCI image.  They live under `profiles:` and stay off by default.

```bash
# One-shot download (~9.5 GB into /var/lib/humanoid-robot/models)
sudo bash /opt/humanoid-robot/fetch-models.sh
# Fetch just the ASR bundle
sudo MODELS=asr bash /opt/humanoid-robot/fetch-models.sh

# Turn the services on
cd /opt/humanoid-robot
docker compose --profile voice --profile rag up -d

# Turn them back off (keeps volumes so restarts don't re-download)
docker compose --profile voice --profile rag down
```

Extra services under those profiles:

- `qdrant` — vector store used by cortex-rag, persisted in the
  `qdrant-data` named volume so the ingested corpus survives image
  swaps.
- `voice` — full mic-to-speaker pipeline (VAD → wake → ASR → TTS).
- `rag`   — grounded QA orchestrator.

Both services mount `/etc/humanoid-robot/{voice,rag}.yaml` from the
host so you can iterate on the stack config without rebuilding the
image.

### Backup + restore

Nightly snapshot the durable state (audit SQLite + Qdrant knowledge
collection) into `/var/backups/humanoid-robot/` — safe on a live stack:

```bash
# manual one-shot
sudo /opt/humanoid-robot/backup.sh
# only the audit DB (skips Qdrant round-trip)
sudo /opt/humanoid-robot/backup.sh --core-only

# nightly at 02:15 UTC, persistent across reboots
sudo systemctl enable --now humanoid-robot-backup.timer

# restore
sudo /opt/humanoid-robot/restore.sh \
    /var/backups/humanoid-robot/humanoid-robot-20261010T021500Z.tar.gz
```

The tarball layout:

```
humanoid-robot-<UTC-ISO8601>.tar.gz
├── safety_audit.sqlite        # SQLite .backup — safe with cortex-core live
└── <collection>-<n>.snapshot  # Qdrant snapshot, one per rag collection
```

Retention keeps the newest `BACKUP_RETAIN` (default 14) tarballs and
prunes older ones. Set `BACKUP_RETAIN=0` to disable pruning.

### Metrics + Grafana + alerts (opt-in)

```bash
cd /opt/humanoid-robot
docker compose --profile metrics up -d
```

- Prometheus  → http://localhost:9090/ — scrapes cortex-core `/metrics`,
  NATS `/varz`, and Qdrant `/metrics` every 5 s (14-day retention).
  Evaluates alert rules from
  `/etc/humanoid-robot/observability/rules/*.yml` and forwards firing
  alerts to Alertmanager. `--web.enable-lifecycle` is on so
  `curl -X POST http://localhost:9090/-/reload` picks up rule edits
  without restarting the container.
- Alertmanager → http://localhost:9093/ — routes alerts. Default
  receiver logs every alert to the container's stdout. Switch to a
  real notifier by editing `/etc/humanoid-robot/alertmanager.env`
  (see `deploy/config/alertmanager.env.example`): uncomment the
  block for `slack` / `discord` / `ntfy` / `webhook`, set the
  webhook URL, restart alertmanager. Critical alerts repeat every
  5 min, warnings every 30 min. Inhibit rules stop CPU/memory
  alerts when the whole process is down.

  ```bash
  sudo $EDITOR /etc/humanoid-robot/alertmanager.env
  docker compose --profile metrics restart alertmanager
  ```
- Grafana     → http://localhost:3000/ — anonymous viewer role is on
  so you can drop into the dashboard without logging in;
  admin/admin gets you edit mode. The "humanoid-robot platform"
  dashboard is auto-provisioned from
  `/etc/humanoid-robot/observability/grafana/dashboards/`. Drop your
  own `.json` next to it and Grafana picks it up within 30 s.

Ports 9090/3000/9093 are bound to `127.0.0.1` only.  Front-face them
with nginx / Cloudflare Tunnel / your VPN of choice when exposing.

Bundled alerts (see `deploy/observability/rules/humanoid-robot.yml`):

- `CortexCoreDown` / `NatsDown` (critical): 30 s downtime.
- `QdrantDown` (warning): 60 s downtime.
- `CortexCoreHighCPU` (warning): rate ≥ 90 % sustained for 5 min.
- `CortexCoreMemoryHigh` (warning): RSS > 1 GiB for 10 min.

### Jetson GPU passthrough (auto-applied)

On any Jetson (any JetPack release), `install-on-robot.sh` detects
the box via `/etc/nv_tegra_release` and writes
`COMPOSE_FILE=docker-compose.yaml:docker-compose.jetson.yaml` into
`/opt/humanoid-robot/.env`. From then on `docker compose` layers the
overlay automatically:

- Adds `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES=all` +
  `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` to the `voice`
  and `rag` services so the Tegra iGPU is visible inside the
  containers.
- Base compose is untouched; nothing enables GPU work outside those
  two services.

Manually enable the overlay elsewhere:

```bash
COMPOSE_FILE=docker-compose.yaml:docker-compose.jetson.yaml \
    docker compose --profile voice --profile rag up -d
```

Prereq — the host has `nvidia-container-runtime` installed and Docker
knows about it. JetPack ships it by default. On stock Ubuntu install
`nvidia-container-toolkit`, then add `"default-runtime": "nvidia"` to
`/etc/docker/daemon.json` (or leave the default runtime alone and
this overlay's `runtime: nvidia` still takes effect).

The overlay also swaps voice/rag onto the arm64-only
`humanoid-robot-base-jetson` image, which is rooted on
`dustynv/l4t-pytorch:r36.2.0` (JetPack 6.0 GA — the community
jetson-containers mirror on Docker Hub, no NGC auth required).
That base ships CUDA + cuDNN + torch built for Tegra, so
`faster-whisper`, BGE-M3 and llama.cpp all reach the iGPU when the
overlay is active. Bump the L4T-PyTorch tag in
`deploy/docker/base-jetson.Dockerfile` alongside any JetPack move.

Switch to the real robot:

```bash
sed -i 's/^HR_ROBOT_ADAPTER__ADAPTER_NAME=.*/HR_ROBOT_ADAPTER__ADAPTER_NAME=unitree_g1_edu/' \
    /opt/humanoid-robot/.env
docker compose -C /opt/humanoid-robot up -d --force-recreate robot-adapter
```

Upgrade:

```bash
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.1.0/' /opt/humanoid-robot/.env
docker compose -C /opt/humanoid-robot pull
docker compose -C /opt/humanoid-robot up -d
```

Images (both `linux/amd64` + `linux/arm64`, published by
`.github/workflows/publish-images.yaml` on every push to main and on
every `vX.Y.Z` tag):

- `ghcr.io/amtilan/humanoid-robot-base`
- `ghcr.io/amtilan/humanoid-robot-dashboard`

Every publish runs three follow-up matrix jobs:

- **Trivy** scans each image for HIGH/CRITICAL fixable CVEs, uploads
  SARIF to the GitHub Security tab (viewable under Security → Code
  scanning), and drops the raw file as a workflow artefact for 30
  days. Findings never block the publish itself — the point is
  visibility, not gating a fix behind a CI flake.
- **Syft** generates an SPDX-JSON SBOM per image, uploaded as an
  artefact with a 90-day retention. Reach for it when responding to a
  supply-chain question (which package version is in `sha-abc1234`?
  which base layer? etc.).
- **Cosign** signs the image manifests keylessly against this
  workflow's OIDC identity (no long-lived key material). A `verify`
  job runs immediately after to confirm the signature landed. See
  "Signature verification" below for the operator-side check.

### Signature verification (fail-closed)

`install-on-robot.sh` verifies every image's signature against this
repo's `publish-images.yaml` workflow identity **before** running
`docker compose pull`. If verification fails — or `cosign` is missing —
the installer aborts, so an unsigned or hijacked tag never reaches the
local image store.

Install cosign
([docs.sigstore.dev](https://docs.sigstore.dev/cosign/installation/))
before running the installer. The installer prints the exact `curl`
lines it needs (linux-amd64 and linux-arm64) if it can't find the
binary.

Escape hatch — dev builds that were never pushed to GHCR:

```bash
curl -sSL .../install-on-robot.sh | sudo bash -s -- --skip-verify
# or set HR_INSTALL_SKIP_VERIFY=1
```

Manual re-verification at any time (also runs before upgrades):

```bash
IMAGE_TAG=v1.0.0 bash /opt/humanoid-robot/verify-images.sh
```

`verify-images.sh` accepts explicit image refs for one-off checks:

```bash
bash /opt/humanoid-robot/verify-images.sh \
    ghcr.io/amtilan/humanoid-robot-base:v1.0.0
```

Any deviation (wrong repo, wrong workflow, wrong identity, missing
signature) causes the script to exit 4 and prints which image
failed.

**`.sig` visibility (auto-fixed).** GHCR gives freshly-created `.sig`
companion packages the user's default visibility (usually private)
even when the main image is public — cosign then 404s on the sig
manifest and the fail-closed installer refuses to pull. The publish
workflow now runs a `gh api PATCH` step right after `cosign sign`
that flips the sig package to public, so verification works
end-to-end from the first tag onward. The step is best-effort: on
first-ever publish the package indexer can lag the API call, so if
you see a `::warning::visibility flip failed` line, flip it manually
at `https://github.com/users/<owner>/packages/container/<name>%2Fsha256-XXXX.sig/settings`
or re-run the workflow.

### Cutting a release

Tag-based releases are driven by `.github/workflows/release.yaml`
(manual trigger only — no accidental releases on merge).

```bash
# Local dry-run preview of the changelog
bash deploy/scripts/preview-release.sh v1.0.0

# Trigger the workflow from the Actions tab or via gh CLI:
gh workflow run release --field version=v1.0.0 --field pre_release=false
# Optional dry-run first:
gh workflow run release --field version=v1.0.0 --field dry_run=true
```

The workflow:

1. Validates the version is strict semver (`vMAJOR.MINOR.PATCH[-pre]`).
2. Rejects existing tags — releases are immutable.
3. Generates a changelog from `git log <prev-tag>..HEAD`, filters out
   `Merge`/`Bump` noise.
4. Creates an annotated tag + GitHub Release with that body.
5. The tag push triggers `publish-images.yaml`, which builds the
   multi-arch OCI images and publishes them under the same version.

Robot upgrade after a release:

```bash
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.0.0/' /opt/humanoid-robot/.env
docker compose -C /opt/humanoid-robot pull
docker compose -C /opt/humanoid-robot up -d
```

## Local compose stack

## Local compose stack

Everything below is fake — no vendor SDK, no models, no real robot.
The stack exists so an operator or a new contributor can `docker
compose up` and see the dashboard talking to a mock adapter over
NATS.

```bash
docker compose -f deploy/docker-compose.yaml up --build
```

- Dashboard  → http://localhost:8081/
- cortex-core → http://localhost:8080/ (also proxied through the
  dashboard at `/api/`)
- NATS       → localhost:4222 (bus) + 8222 (monitoring)

Ports 8080/8081 are bound to `127.0.0.1` on purpose — the stack has
no auth yet and shouldn't be reachable from the LAN by default.

### Services

| Service         | Command                                                  | Notes |
|-----------------|----------------------------------------------------------|-------|
| `nats`          | `nats -c /etc/nats/nats.conf`                            | JetStream on, monitoring on :8222 |
| `core`          | `uvicorn humanoid_robot.core.app:app_from_env --factory` | cortex-core FastAPI orchestrator |
| `robot-adapter` | `cortex-robot-adapter run mock`                          | MockRobotAdapter — no G1 SDK |
| `dashboard`     | `nginx`                                                  | Serves `web/dashboard` dist, proxies `/api` to `core` |

### Health

```bash
curl http://localhost:8080/api/v1/system/health/live
curl http://localhost:8080/api/v1/system/health/ready
curl http://localhost:8222/                # NATS monitoring
```

### Overriding settings

Services layer `pydantic-settings`; env vars prefixed with `HR_`
override the defaults. Nested config uses `__`:

```bash
HR_OBSERVABILITY__LOG_LEVEL=DEBUG docker compose up core
HR_ROBOT_ADAPTER__ADAPTER_CONFIG='{"hand_kind":"dex3"}' docker compose up robot-adapter
```

### What is NOT in the stack yet

Deliberately excluded from R1 so the stack stays boot-in-30-s on a
developer laptop:

- `cortex-voice` and `cortex-rag` — need model bundles (Qwen,
  faster-whisper, Piper, BGE-M3) that we don't want in the base image
- `cortex-ingest` — usable but pointless without RAG
- Qdrant — same reason
- Real Unitree G1 SDK
- systemd, Ansible, OTA channel — Phase 9 R2+

## Jetson bring-up (systemd)

The `systemd/` folder ships four unit files and one umbrella target:

- `cortex-core.service` — FastAPI orchestrator + safety stack (audit
  SQLite lives at `/var/lib/humanoid-robot/safety_audit.sqlite`)
- `cortex-robot-adapter.service` — dispatcher + telemetry pump
  (`unitree_g1_edu` on the robot; `mock` on the bench)
- `cortex-voice.service` — mic → VAD/wake/ASR pipeline + TTS speaker
- `cortex-rag.service` — grounded QA (LLM + retrieval + guardrails)
- `humanoid-robot.target` — one-shot start/stop for all four

Every unit is hardened (`NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp`, kernel/cgroup protections) and runs as
the `humanoid-robot` system user. Only these paths are writable:

- `/var/lib/humanoid-robot` — models, RAG state, audit DB
- `/var/log/humanoid-robot` — reserved for future direct-file logs
  (default is journald)

### Install

```bash
git clone https://github.com/Amtilan/humanoid-robot.git /tmp/humanoid-robot
cd /tmp/humanoid-robot
sudo bash deploy/scripts/bootstrap-jetson.sh
```

`bootstrap-jetson.sh` is idempotent: creates the user, sets up the
state dirs, installs the units + reference env files (never
overwrites), and reloads systemd. It DOES NOT start the services —
you review `/etc/humanoid-robot/*.env` first, install `nats-server`,
then:

```bash
sudo systemctl enable --now nats-server humanoid-robot.target
journalctl -u cortex-core -u cortex-robot-adapter -u cortex-voice -u cortex-rag -f
```

### Env-file overrides

Each service reads
`EnvironmentFile=-/etc/humanoid-robot/<service>.env` (the `-` means
optional for core/adapter, mandatory for voice/rag because they need
model paths).  The `.example` files under `deploy/config/` document
every knob; they get installed with mode `0640` owned by
`root:humanoid-robot` so credentials never leak to the world.

### Reference paths

| Path | Purpose |
|------|---------|
| `/opt/humanoid-robot`           | Cloned release + `uv sync`'d `.venv` |
| `/etc/humanoid-robot/*.env`     | Per-service env overrides |
| `/var/lib/humanoid-robot/models`| LLM/ASR/TTS/embedder weights |
| `/var/lib/humanoid-robot/rag`   | RAG working data (Qdrant if colocated) |
| `/var/lib/humanoid-robot/safety_audit.sqlite` | Audit log |
| `/var/log/humanoid-robot`       | Reserved (services log to journald) |
