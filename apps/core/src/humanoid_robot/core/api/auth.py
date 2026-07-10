"""Bearer-token gate — applied as a Starlette middleware.

Design notes:
  * Opt-in: an empty settings token leaves the API open (same behaviour
    as every previous release, keeps dev laptops frictionless).
  * All ``/api/v1/system/health/*`` and ``/api/v1/system/info`` requests
    bypass the check so k8s / systemd / docker healthchecks keep
    working without the token.
  * WebSocket auth accepts either an ``Authorization: Bearer <t>`` header
    (native for JS clients that already carry a token) or a ``?token=<t>``
    query string (fallback for browser code that can't set WS headers).
  * ``/metrics`` stays unauthenticated — Prometheus scrapes cortex-core
    inside the compose network, no external exposure.
  * Failed-auth requests from a given client accrue in a sliding
    window; once the client crosses the configured threshold every
    further request from that client returns 429 until the window
    empties, regardless of what token they now present.  A successful
    auth resets that client's counter, so a legitimate operator who
    fat-fingers their token a few times isn't locked out for a full
    minute.
"""

from __future__ import annotations

import hmac
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_HEALTH_PREFIXES = (
    "/api/v1/system/health",
    "/api/v1/system/info",
)


class UnauthAttemptLimiter:
    """Per-client sliding window over recent failed-auth attempts.

    The block decision is intentionally independent of what token the
    caller now presents — an attacker who's over budget must not be able
    to tell whether a specific guess was correct by observing 401 vs
    429 differences.  Legitimate callers who cross the threshold clear
    it by waiting (successful auth also clears their bucket).
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        window_s: float,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts < 0:
            raise ValueError("max_attempts must be >= 0")
        if window_s <= 0.0:
            raise ValueError("window_s must be > 0.0")
        self._max = max_attempts
        self._window = window_s
        self._now = time_fn
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def register_failure(self, client: str) -> None:
        now = self._now()
        with self._lock:
            q = self._events.setdefault(client, deque())
            self._evict(q, now)
            q.append(now)

    def reset(self, client: str) -> None:
        with self._lock:
            self._events.pop(client, None)

    def blocked(self, client: str) -> tuple[bool, float]:
        """Return (is_blocked, retry_after_seconds).

        retry_after is the wall time until the *earliest* recorded
        failure ages out of the window — after that the client would
        drop below the threshold and be allowed to try again.
        """
        if self._max == 0:
            return (True, self._window)
        now = self._now()
        with self._lock:
            q = self._events.get(client)
            if q is None:
                return (False, 0.0)
            self._evict(q, now)
            if len(q) < self._max:
                return (False, 0.0)
            retry_after = max(0.0, q[0] + self._window - now)
            return (True, retry_after)

    def _evict(self, q: deque[float], now: float) -> None:
        cutoff = now - self._window
        while q and q[0] < cutoff:
            q.popleft()


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Enforces the configured bearer token on every non-health API request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        token: str,
        rate_limiter: UnauthAttemptLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self._token = token
        self._rate = rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._is_protected(request):
            return await call_next(request)

        client = _client_key(request)

        if self._rate is not None:
            blocked, retry_after = self._rate.blocked(client)
            if blocked:
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
                    content={"detail": "too many failed auth attempts; slow down"},
                )

        presented = _presented_token(request)
        if not presented or not _matches(self._token, presented):
            if self._rate is not None:
                self._rate.register_failure(client)
            return JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="cortex-core"'},
                content={"detail": "missing or invalid bearer token"},
            )
        if self._rate is not None:
            self._rate.reset(client)
        return await call_next(request)

    def _is_protected(self, request: Request) -> bool:
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return False
        return not any(path.startswith(pref) for pref in _HEALTH_PREFIXES)


def _presented_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value
    query = request.query_params.get("token")
    return query or None


def _matches(expected: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8"))


def _client_key(request: Request) -> str:
    # X-Forwarded-For is trusted here because the compose stack binds
    # cortex-core to 127.0.0.1 — any XFF chain we see comes from a
    # loopback reverse proxy on the same host, not an untrusted edge.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def enforce_ws_token(expected: str, header: str | None, query_token: str | None) -> bool:
    """Auth check for WebSocket handshakes.

    Called by the events WS handler *before* ``.accept()`` — a False
    return means "close the socket with 4401" (custom close code that
    JS clients can distinguish from network errors).
    """
    if not expected:
        return True
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and _matches(expected, value):
            return True
    return bool(query_token and _matches(expected, query_token))
