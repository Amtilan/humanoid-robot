"""NATS + JetStream `EventBusPort` implementation.

Design notes
------------
- Serialisation: `event.model_dump_json().encode("utf-8")` — no extra wrapping.
  Routing metadata lives in NATS message headers, not in the payload, so
  external tools reading the stream see clean domain JSON.
- Headers:
    hr-schema-version: str(int)
    hr-type-name:      Class name (Python-side hint; the routing key is the
                       subject, not the class name)
- Durable subscriptions use JetStream; ephemeral use core NATS.
- Cancellation of a subscription cancels its background consumer task and
  unsubscribes cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from pydantic import ValidationError

import nats
from humanoid_robot.adapters.nats.registry import SUBJECT_TO_EVENT
from humanoid_robot.events import BaseEvent
from humanoid_robot.ports.event_bus import EventBusPort, EventHandler, Subscription
from nats.aio.client import Client as NatsClient
from nats.errors import TimeoutError as NatsTimeoutError

if TYPE_CHECKING:
    from nats.aio.msg import Msg
    from nats.aio.subscription import Subscription as NatsSub

_LOG = logging.getLogger(__name__)

_HEADER_SCHEMA_VERSION = "hr-schema-version"
_HEADER_TYPE_NAME = "hr-type-name"


@dataclass(slots=True, frozen=True)
class NatsEventBusConfig:
    """Configuration for `NatsEventBus`."""

    servers: tuple[str, ...] = ("nats://127.0.0.1:4222",)
    name: str = "humanoid-robot"
    connect_timeout_s: float = 5.0
    reconnect_time_wait_s: float = 1.0
    max_reconnect_attempts: int = -1
    user_credentials: str | None = None
    tls_ca: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    # If true, close() will drain in-flight deliveries before disconnecting.
    drain_on_close: bool = True
    # Publish timeout so `publish()` cannot hang forever.
    publish_timeout_s: float = 5.0


class _NatsSubscription:
    """`Subscription` implementation that also holds the background consumer."""

    __slots__ = ("_cancelled", "_sub", "_task")

    def __init__(self, sub: NatsSub, task: asyncio.Task[None]) -> None:
        self._sub = sub
        self._task = task
        self._cancelled = False

    async def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        with contextlib.suppress(Exception):
            await self._sub.unsubscribe()


@dataclass(slots=True)
class NatsEventBus(EventBusPort):
    """NATS-backed `EventBusPort`."""

    config: NatsEventBusConfig = field(default_factory=NatsEventBusConfig)
    _client: NatsClient | None = None
    _subs: list[_NatsSubscription] = field(default_factory=list)
    _closed: bool = False

    async def connect(self) -> Self:
        """Open the connection. Idempotent."""
        if self._client is not None and self._client.is_connected:
            return self
        # nats-py 2.7+ dropped the individual tls_*_file kwargs in favour
        # of a pre-built ssl.SSLContext passed via `tls=`. Only build one
        # when the operator actually configured TLS material — plain
        # `nats://` connections skip the whole knot.
        options: dict[str, object] = {
            "servers": list(self.config.servers),
            "name": self.config.name,
            "connect_timeout": self.config.connect_timeout_s,
            "reconnect_time_wait": self.config.reconnect_time_wait_s,
            "max_reconnect_attempts": self.config.max_reconnect_attempts,
        }
        if self.config.user_credentials:
            options["user_credentials"] = self.config.user_credentials
        tls_ctx = _build_tls_context(
            ca=self.config.tls_ca,
            cert=self.config.tls_cert,
            key=self.config.tls_key,
        )
        if tls_ctx is not None:
            options["tls"] = tls_ctx
        self._client = await nats.connect(**options)  # type: ignore[arg-type]
        return self

    async def publish(self, event: BaseEvent) -> None:
        if self._closed:
            msg = "bus is closed"
            raise RuntimeError(msg)
        client = self._require_client()
        payload = event.model_dump_json().encode("utf-8")
        headers = {
            _HEADER_SCHEMA_VERSION: str(type(event).schema_version),
            _HEADER_TYPE_NAME: type(event).__name__,
        }
        try:
            await asyncio.wait_for(
                client.publish(
                    subject=type(event).subject,
                    payload=payload,
                    headers=headers,
                ),
                timeout=self.config.publish_timeout_s,
            )
        except (TimeoutError, NatsTimeoutError) as exc:
            msg = f"publish to {type(event).subject} timed out"
            raise TimeoutError(msg) from exc

    async def subscribe(
        self,
        subject_pattern: str,
        handler: EventHandler,
        *,
        durable_name: str | None = None,
    ) -> Subscription:
        if self._closed:
            msg = "bus is closed"
            raise RuntimeError(msg)
        client = self._require_client()

        # We currently model durable_name at the core NATS level via
        # queue-group semantics; a full JetStream pull-consumer path will come
        # in the next milestone once we introduce persistent streams. The NATS
        # client types expect a non-optional queue string; empty string == no
        # queue group.
        queue = durable_name or ""

        raw_sub: NatsSub = await client.subscribe(subject=subject_pattern, queue=queue)

        async def _consume() -> None:
            async for msg in raw_sub.messages:
                try:
                    event = _decode(msg)
                except Exception:
                    _LOG.exception("failed to decode message on %s", msg.subject)
                    continue
                if event is None:
                    continue
                try:
                    await handler(event)
                except Exception:
                    _LOG.exception("handler raised on %s", msg.subject)

        task = asyncio.create_task(_consume(), name=f"nats-consumer[{subject_pattern}]")
        sub = _NatsSubscription(sub=raw_sub, task=task)
        self._subs.append(sub)
        return sub

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for sub in self._subs:
            await sub.cancel()
        self._subs.clear()
        client = self._client
        if client is None:
            return
        if self.config.drain_on_close:
            with contextlib.suppress(Exception):
                await client.drain()
        with contextlib.suppress(Exception):
            await client.close()
        self._client = None

    def _require_client(self) -> NatsClient:
        if self._client is None:
            msg = "NatsEventBus is not connected; call .connect() first"
            raise RuntimeError(msg)
        return self._client


def _build_tls_context(
    *,
    ca: str | None,
    cert: str | None,
    key: str | None,
) -> ssl.SSLContext | None:
    """Assemble the SSLContext nats-py 2.7+ expects, or None when no TLS."""
    if not (ca or cert or key):
        return None
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    return ctx


def _decode(msg: Msg) -> BaseEvent | None:
    """Decode a raw NATS message into a `BaseEvent` via the class registry.

    Returns None for subjects that are not in the registry (e.g. subscriber
    used a wildcard broader than the platform's known catalog). This is not
    an error — subscribers who care about unknown types can subscribe more
    narrowly.
    """
    cls = SUBJECT_TO_EVENT.get(msg.subject)
    if cls is None:
        _LOG.debug("unknown subject %s, no event class registered", msg.subject)
        return None
    try:
        return cls.model_validate_json(msg.data)
    except ValidationError as exc:
        _LOG.warning(
            "payload on %s failed schema validation for %s: %s",
            msg.subject,
            cls.__name__,
            exc,
        )
        return None
