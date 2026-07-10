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
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_HEALTH_PREFIXES = (
    "/api/v1/system/health",
    "/api/v1/system/info",
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Enforces the configured bearer token on every non-health API request."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._is_protected(request):
            return await call_next(request)
        if not _presented_token(request) or not _matches(self._token, _presented_token(request)):
            return JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="cortex-core"'},
                content={"detail": "missing or invalid bearer token"},
            )
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
