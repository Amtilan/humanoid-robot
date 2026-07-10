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

### Metrics + Grafana (opt-in)

```bash
cd /opt/humanoid-robot
docker compose --profile metrics up -d
```

- Prometheus  → http://localhost:9090/ — scrapes cortex-core `/metrics`,
  NATS `/varz`, and Qdrant `/metrics` every 5 s (14-day retention).
- Grafana     → http://localhost:3000/ — anonymous viewer role is on
  so you can drop into the dashboard without logging in;
  admin/admin gets you edit mode. The "humanoid-robot platform"
  dashboard is auto-provisioned from
  `/etc/humanoid-robot/observability/grafana/dashboards/`. Drop your
  own `.json` next to it and Grafana picks it up within 30 s.

Ports 9090/3000 are bound to `127.0.0.1` only.  Front-face them
with nginx / Cloudflare Tunnel / your VPN of choice when exposing.

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
