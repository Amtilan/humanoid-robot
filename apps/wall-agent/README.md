# cortex-wall-agent

Control agent for the presentation video wall (the customer's `Factories.exe`
Unity application, «MinTrans»). Runs next to the wall application — on the
wall's Windows PC in production, or anywhere as a simulator during autonomous
testing — and exposes a tiny HTTP API the robot calls over the local network.

## API

| Route | Description |
|---|---|
| `POST /wall/command` | Execute a `WallCommand` (`open_section` / `navigate`) |
| `GET /wall/state` | Current screen + slide (simulator: exact; sendinput: best-effort tracking) |
| `GET /healthz` | Readiness probe |

Optional shared-secret auth: start with `--token` (or `HR_WALL_AGENT_TOKEN`);
clients then send `X-Wall-Token`.

## Drivers

- `sim` — in-memory model of the wall app (12 sections, categories, slides).
  Used for autonomous testing and CI; deployed as the `wall-agent` compose
  service so the whole voice → intent → wall pipeline can be exercised
  without the physical wall.
- `sendinput` — Windows input emulation. Focuses the wall-app window and
  replays a per-command action list (mouse clicks at normalized coordinates,
  key presses — the app itself only listens to PgUp/PgDn for slides, section
  screens are switched by clicking its UI buttons). The click map is a JSON
  file calibrated once on-site: see `deploy/wall-agent/mapping.example.json`.

## Run

```bash
cortex-wall-agent --driver sim --port 8093
cortex-wall-agent --driver sendinput --mapping C:\wall\mapping.json --token SECRET
```
