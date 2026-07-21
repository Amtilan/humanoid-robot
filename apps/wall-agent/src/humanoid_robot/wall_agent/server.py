"""Stdlib HTTP server exposing the wall driver on the local network.

Mirrors the ``camera_mjpeg`` appliance pattern: pure ``http.server``, no web
framework — the agent must also run as a single-file install on the wall's
Windows PC.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pydantic import ValidationError

from humanoid_robot.domain.wall import WallCommand
from humanoid_robot.wall_agent.drivers import WallDriver

log = logging.getLogger(__name__)

_MAX_BODY_BYTES = 64 * 1024


def make_handler(driver: WallDriver, token: str = "") -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to a driver instance."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "cortex-wall-agent"

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not token:
                return True
            return self.headers.get("X-Wall-Token", "") == token

        def do_GET(self) -> None:
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok", "driver": driver.name})
            elif self.path == "/wall/state":
                self._send_json(200, driver.state())
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            if self.path != "/wall/command":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > _MAX_BODY_BYTES:
                self._send_json(400, {"error": "bad content length"})
                return
            try:
                command = WallCommand.model_validate_json(self.rfile.read(length))
            except ValidationError as exc:
                self._send_json(400, {"error": "invalid command", "detail": str(exc)})
                return
            result = driver.execute(command)
            self._send_json(200, result.model_dump(mode="json"))

        def log_message(self, format: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), format % args)

    return Handler


def serve(
    driver: WallDriver,
    *,
    host: str = "0.0.0.0",  # noqa: S104 — LAN appliance, token-gated
    port: int = 8093,
    token: str = "",
) -> ThreadingHTTPServer:
    """Create (but do not run) the HTTP server; caller invokes serve_forever."""
    handler = make_handler(driver, token)
    return ThreadingHTTPServer((host, port), handler)
