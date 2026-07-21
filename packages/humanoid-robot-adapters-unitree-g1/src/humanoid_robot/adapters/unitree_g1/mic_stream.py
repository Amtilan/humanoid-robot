"""Live mic monitor — stream the G1 head-mic multicast to the browser.

The G1 microphone multicasts 16 kHz mono PCM16 on a UDP group (same source the
voice pipeline consumes). This serves it as a streaming WAV over HTTP so an
operator can open the dashboard and *hear* what the robot hears live — handy
for confirming mic levels / diagnosing "the robot can't hear me".

Pure stdlib (no extra deps), runs inside the adapter container on host net so
the multicast on eth10 is reachable.

    python -m humanoid_robot.adapters.unitree_g1.mic_stream \
        --interface-ip 192.168.123.164 --port 8092

Routes:
    GET /mic/stream?source=usb&gain=N
        -> streaming audio/wav of the USB (ASR) microphone, mirrored onto the
           NATS bus by the voice service while we keep the tap alive. This is
           what the robot actually LISTENS to; default source.
    GET /mic/stream?source=builtin&gain=N
        -> the G1 built-in head mic (DDS multicast). Quiet — gain default 20x.
    GET /healthz            -> 200
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
import os
import socket
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

_LOG = logging.getLogger("humanoid_robot.adapters.unitree_g1.mic_stream")

_GROUP = "239.168.123.161"  # pragma: allowlist secret
_PORT = 5555
_SAMPLE_RATE = 16_000
_DEFAULT_GAIN = 20.0
_USB_DEFAULT_GAIN = 1.0
_RECV_BYTES = 8192

# The voice service (host net) mirrors mic frames while we keep the tap
# alive with control keepalives; see AudioMonitorControl/AudioMonitorFrame.
_NATS_URL = os.environ.get("HR_MIC_NATS_URL", "nats://127.0.0.1:4222")
_FRAME_SUBJECT = "audio.monitor.frame"
_CONTROL_SUBJECT = "audio.monitor.control"
_KEEPALIVE_S = 10.0
_TAP_TTL_S = 30.0


def _join_multicast(interface_ip: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", _PORT))
    mreq = socket.inet_aton(_GROUP) + socket.inet_aton(interface_ip)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(2.0)
    return sock


def _streaming_wav_header() -> bytes:
    """A WAV header with a 'streaming' (max) data size so browsers keep playing."""
    data_size = 0xFFFFFFFF - 44
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 0xFFFFFFFF),
            b"WAVE",
            b"fmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, _SAMPLE_RATE, _SAMPLE_RATE * 2, 2, 16),
            b"data",
            struct.pack("<I", data_size),
        ]
    )


def _apply_gain(pcm: bytes, gain: float) -> bytes:
    if gain == 1.0:
        return pcm
    count = len(pcm) // 2
    if count == 0:
        return pcm
    samples = struct.unpack(f"<{count}h", pcm)
    scaled = [max(-32768, min(32767, int(s * gain))) for s in samples]
    return struct.pack(f"<{count}h", *scaled)


def _make_handler(interface_ip: str, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            _LOG.debug("%s - %s", self.address_string(), fmt % args)

        def _authed(self, query: str) -> bool:
            if not token:
                return True
            # nginx proxies straight past core's auth gate, so enforce the
            # shared token here; <audio> can't set headers, hence ?token=.
            presented = parse_qs(query).get("token", [""])[0]
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                presented = presented or header[len("Bearer ") :]
            return presented == token

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._text(200, "ok")
                return
            if not self._authed(parsed.query):
                self._text(401, "unauthorized")
                return
            if not parsed.path.endswith("/stream"):
                self._text(404, "not found")
                return
            query = parse_qs(parsed.query)
            source = query.get("source", ["usb"])[0]
            gain = _USB_DEFAULT_GAIN if source == "usb" else _DEFAULT_GAIN
            q = query.get("gain")
            if q:
                with contextlib.suppress(ValueError):
                    gain = max(1.0, min(500.0, float(q[0])))
            if source == "usb":
                self._serve_usb(gain)
            else:
                self._serve_stream(gain)

        def _serve_stream(self, gain: float) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            sock = _join_multicast(interface_ip)
            try:
                self.wfile.write(_streaming_wav_header())
                while True:
                    try:
                        data, _ = sock.recvfrom(_RECV_BYTES)
                    except TimeoutError:
                        continue
                    self.wfile.write(_apply_gain(data, gain))
            except (BrokenPipeError, ConnectionResetError):
                return
            finally:
                sock.close()

        def _serve_usb(self, gain: float) -> None:
            """Stream the USB (ASR) mic mirrored onto the bus by the voice
            service. We keep the tap alive with periodic control events."""
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                asyncio.run(_pump_usb(self.wfile, gain))
            except (BrokenPipeError, ConnectionResetError):
                return

        def _text(self, code: int, msg: str) -> None:
            body = msg.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


async def _pump_usb(wfile: Any, gain: float) -> None:
    # Local imports: the builtin (DDS) path stays pure-stdlib.
    import nats

    from humanoid_robot.domain.shared import new_correlation_id
    from humanoid_robot.events import AudioMonitorControl
    from humanoid_robot.events.base import EventMetadata

    nc = await nats.connect(_NATS_URL)
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

    async def on_frame(msg: Any) -> None:
        with contextlib.suppress(Exception):
            pcm = base64.b64decode(json.loads(msg.data)["pcm_b64"])
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()  # drop oldest, keep realtime
            queue.put_nowait(pcm)

    async def keep_tap_alive() -> None:
        while True:
            event = AudioMonitorControl(
                meta=EventMetadata(correlation_id=new_correlation_id(), producer="g1-mic-monitor"),
                enabled=True,
                ttl_s=_TAP_TTL_S,
            )
            with contextlib.suppress(Exception):
                await nc.publish(_CONTROL_SUBJECT, event.model_dump_json().encode())
            await asyncio.sleep(_KEEPALIVE_S)

    sub = await nc.subscribe(_FRAME_SUBJECT, cb=on_frame)
    keepalive = asyncio.create_task(keep_tap_alive())
    try:
        wfile.write(_streaming_wav_header())
        while True:
            try:
                pcm = await asyncio.wait_for(queue.get(), timeout=2.0)
            except TimeoutError:
                continue
            wfile.write(_apply_gain(pcm, gain))
    finally:
        keepalive.cancel()
        with contextlib.suppress(Exception):
            await sub.unsubscribe()
            await nc.close()


def serve(interface_ip: str, port: int, token: str = "") -> None:
    httpd = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(interface_ip, token))  # noqa: S104
    _LOG.info("G1 mic monitor on :%d (multicast %s via %s)", port, _GROUP, interface_ip)
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="G1 mic live monitor (streaming WAV)")
    parser.add_argument(
        "--interface-ip", default=os.environ.get("HR_MIC_IFACE_IP", "192.168.123.164")
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("HR_MIC_PORT", "8092")))
    parser.add_argument("--token", default=os.environ.get("HR_AUTH__TOKEN", ""))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    serve(args.interface_ip, args.port, args.token)


if __name__ == "__main__":
    main()
