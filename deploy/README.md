# Deployment artifacts

- `systemd/` — unit files installed under `/etc/systemd/system/` on the robot.
- `docker/` — compose stacks for local development (NATS, later Prometheus,
  Grafana, Loki, Tempo).
- `config/` — reference configuration files. Deploy copies to
  `/etc/humanoid-robot/`.
- `mender/` (planned) — OTA artifact definitions.
- `flashing/` (planned) — Jetson flashing scripts.

## Bringing up cortex-core on a Jetson

1. Install `nats-server` as a system service (see [NATS install docs](
   https://docs.nats.io/running-a-nats-service/introduction/installation)).
2. Create a dedicated `humanoid-robot` user, home
   `/opt/humanoid-robot`, and clone the release artefact there.
3. `uv sync --all-packages` inside `/opt/humanoid-robot`.
4. Copy `deploy/config/base.yaml` to `/etc/humanoid-robot/config.yaml` and
   edit as needed.
5. Copy `deploy/systemd/cortex-core.service` to `/etc/systemd/system/`.
6. `systemctl enable --now cortex-core`.

## Local development

```bash
docker compose -f deploy/docker/nats.compose.yaml up -d
uv run cortex-core serve
```
