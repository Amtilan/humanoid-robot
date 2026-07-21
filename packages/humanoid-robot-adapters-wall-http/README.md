# humanoid-robot-adapters-wall-http

`WallControlPort` implementation that talks to the video-wall control agent
(`cortex-wall-agent`) over plain HTTP on the local network.

The agent runs next to the wall application (Windows PC of the presentation
wall, or the built-in simulator during autonomous testing) and exposes:

- `POST /wall/command` — execute a `WallCommand`
- `GET /healthz` — readiness probe

Failures never raise: connection errors map to `outcome=unreachable`,
HTTP errors to `outcome=rejected`.
