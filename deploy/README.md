# Deployment

Everything under `deploy/` runs the platform outside a developer's uv
workspace: Docker Compose for local integration testing, and (in
later rounds) systemd units + Ansible for the Jetson.

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

## Bringing up cortex-core on a Jetson (future rounds)

1. Install `nats-server` as a system service (see [NATS install docs](
   https://docs.nats.io/running-a-nats-service/introduction/installation)).
2. Create a dedicated `humanoid-robot` user, home `/opt/humanoid-robot`,
   clone the release artefact there.
3. `uv sync --all-packages` inside `/opt/humanoid-robot`.
4. Copy `deploy/config/base.yaml` to `/etc/humanoid-robot/config.yaml`
   and edit as needed.
5. Copy `deploy/systemd/*.service` to `/etc/systemd/system/`.
6. `systemctl enable --now cortex-core cortex-robot-adapter …`.
