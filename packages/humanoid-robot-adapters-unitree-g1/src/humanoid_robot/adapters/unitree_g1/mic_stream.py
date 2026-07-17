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
    GET /mic/stream?gain=N  -> streaming audio/wav (gain default 20x — the raw
                               mic is quiet; amplify so faint audio is audible)
    GET /healthz            -> 200
"""

from __future__ import annotations

import argparse
import contextlib
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
_RECV_BYTES = 8192


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
            gain = _DEFAULT_GAIN
            q = parse_qs(parsed.query).get("gain")
            if q:
                with contextlib.suppress(ValueError):
                    gain = max(1.0, min(500.0, float(q[0])))
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

        def _text(self, code: int, msg: str) -> None:
            body = msg.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


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
