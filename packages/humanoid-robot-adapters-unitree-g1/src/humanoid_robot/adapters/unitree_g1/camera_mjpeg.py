"""MJPEG bridge for the Unitree G1 front camera.

The G1's cameras are wired to the robot's main computer, not to our Jetson —
there is no local /dev/video or CSI sensor here (nvargus reports "no cameras").
The vendor exposes the front camera as JPEG frames over DDS through the
``VideoClient`` request/response service (the same one the Unitree mobile app
uses). This module polls that service on a single background thread and fans
the latest frame out to any number of HTTP viewers as an ``multipart/x-mixed-
replace`` MJPEG stream — the browser-native way to show "the robot's eyes"
with a plain ``<img>`` tag.

It runs inside the adapter container, which already has host networking (DDS
multicast on eth10) and the ``unitree_sdk2py`` SDK. Pure stdlib HTTP server —
no fastapi/aiohttp dependency added to the adapter.

Standalone:
    python -m humanoid_robot.adapters.unitree_g1.camera_mjpeg \
        --interface eth10 --port 8091

Routes:
    GET /camera/{id}/stream    -> multipart/x-mixed-replace MJPEG
    GET /camera/{id}/snapshot  -> single image/jpeg
    GET /healthz               -> 200 when the capture loop has a fresh frame
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_LOG = logging.getLogger("humanoid_robot.adapters.unitree_g1.camera_mjpeg")

_BOUNDARY = "frame"
# The vendor GetImageSample is a blocking DDS round-trip; ~12 fps keeps the bus
# calm while still feeling live. Tune via --fps.
_DEFAULT_FPS = 12.0
# If a poll fails (robot busy / transient DDS), back off briefly before retry
# so we don't spin the bus.
_ERROR_BACKOFF_S = 0.5


class FrameHub:
    """Single VideoClient poller; publishes the latest JPEG to N viewers.

    One capture loop feeds every viewer, so 5 open browser tabs cost the DDS
    bus exactly one stream, not five.
    """

    def __init__(self, client: Any, fps: float = _DEFAULT_FPS) -> None:
        self._client = client
        self._period = 1.0 / fps if fps > 0 else 0.0
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._stamp = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="g1-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._cond:
            self._cond.notify_all()

    def _run(self) -> None:
        while self._running:
            t0 = time.monotonic()
            try:
                code, data = self._client.GetImageSample()
            except Exception:  # noqa: BLE001 — never let a poll kill the loop
                _LOG.exception("GetImageSample raised")
                time.sleep(_ERROR_BACKOFF_S)
                continue
            if code != 0 or not data:
                _LOG.warning("GetImageSample returned code=%s", code)
                time.sleep(_ERROR_BACKOFF_S)
                continue
            frame = bytes(data)
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._stamp = time.monotonic()
                self._cond.notify_all()
            # Pace to the target fps (account for the round-trip time already spent).
            if self._period:
                slack = self._period - (time.monotonic() - t0)
                if slack > 0:
                    time.sleep(slack)

    def snapshot(self, timeout: float = 5.0) -> bytes | None:
        """Return the current frame, waiting up to ``timeout`` for the first."""
        with self._cond:
            if self._frame is None:
                self._cond.wait(timeout)
            return self._frame

    def wait_next(self, last_seq: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        """Block until a frame newer than ``last_seq`` is available."""
        with self._cond:
            if self._seq <= last_seq:
                self._cond.wait(timeout)
            return self._seq, self._frame

    @property
    def healthy(self) -> bool:
        return self._frame is not None and (time.monotonic() - self._stamp) < 5.0


def _make_handler(hub: FrameHub, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter default logging
            _LOG.debug("%s - %s", self.address_string(), fmt % args)

        def _authed(self) -> bool:
            if not token:
                return True
            # Browsers can't set headers on <img>, so accept ?token= too —
            # same fallback the core WS/camera routes use.
            from urllib.parse import parse_qs, urlparse

            q = parse_qs(urlparse(self.path).query)
            presented = q.get("token", [""])[0]
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                presented = presented or header[len("Bearer ") :]
            return presented == token

        def _path(self) -> str:
            from urllib.parse import urlparse

            return urlparse(self.path).path

        def do_GET(self) -> None:  # noqa: N802 — stdlib naming
            path = self._path()
            if path == "/healthz":
                self._send_text(200 if hub.healthy else 503, "ok" if hub.healthy else "no-frame")
                return
            if not self._authed():
                self._send_text(401, "unauthorized")
                return
            # /camera/<id>/stream|snapshot — id is accepted but the G1 exposes a
            # single front camera today, so it's not used to select a sensor.
            if path.endswith("/snapshot"):
                self._serve_snapshot()
            elif path.endswith("/stream"):
                self._serve_stream()
            else:
                self._send_text(404, "not found")

        def _serve_snapshot(self) -> None:
            frame = hub.snapshot()
            if frame is None:
                self._send_text(503, "no frame yet")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)

        def _serve_stream(self) -> None:
            self.send_response(200)
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            last = 0
            try:
                while True:
                    last, frame = hub.wait_next(last)
                    if frame is None:
                        continue
                    self.wfile.write(f"--{_BOUNDARY}\r\n".encode())
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return  # viewer closed the tab; normal

        def _send_text(self, code: int, msg: str) -> None:
            body = msg.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def build_video_client(interface: str, domain: int = 0, timeout_s: float = 3.0) -> Any:
    """Initialise DDS and a ready ``VideoClient`` for the G1 front camera."""
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.video.video_client import VideoClient

    ChannelFactoryInitialize(domain, interface)
    client = VideoClient()
    client.SetTimeout(timeout_s)
    client.Init()
    return client


def serve(interface: str, port: int, fps: float, token: str) -> None:
    client = build_video_client(interface)
    hub = FrameHub(client, fps=fps)
    hub.start()
    handler = _make_handler(hub, token)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)  # noqa: S104 — host-net appliance
    _LOG.info("G1 camera MJPEG bridge on :%d (iface=%s fps=%.1f)", port, interface, fps)
    try:
        httpd.serve_forever()
    finally:
        hub.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Unitree G1 front-camera MJPEG bridge")
    parser.add_argument("--interface", default=os.environ.get("HR_UNITREE_IFACE", "eth10"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HR_CAMERA_PORT", "8091")))
    parser.add_argument("--fps", type=float, default=float(os.environ.get("HR_CAMERA_FPS", _DEFAULT_FPS)))
    parser.add_argument("--token", default=os.environ.get("HR_AUTH__TOKEN", ""))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    serve(args.interface, args.port, args.fps, args.token)


if __name__ == "__main__":
    main()
