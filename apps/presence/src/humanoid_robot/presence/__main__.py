"""CLI entrypoint: ``cortex-presence --snapshot-url http://...:8091/camera/front/snapshot``."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal

import httpx

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.observability import configure_logging, get_logger
from humanoid_robot.presence.runner import PresenceRunner

log = get_logger("cortex-presence")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cortex-presence",
        description="Camera-based visitor detection for the presenter robot.",
    )
    parser.add_argument(
        "--snapshot-url",
        default=os.environ.get(
            "HR_PRESENCE_SNAPSHOT_URL",
            "http://host.docker.internal:8091/camera/front/snapshot",
        ),
    )
    parser.add_argument(
        "--nats-url",
        default=os.environ.get("HR_PRESENCE_NATS_URL", "nats://nats:4222"),
    )
    parser.add_argument("--threshold", type=float, default=0.02)
    parser.add_argument("--interval-s", type=float, default=0.5)
    parser.add_argument("--rearm-s", type=float, default=30.0)
    parser.add_argument(
        "--token",
        # The camera bridge enforces the platform token itself (nginx is
        # bypassed on the LAN), so presence forwards it as ?token=.
        default=os.environ.get("HR_PRESENCE_TOKEN", os.environ.get("HR_AUTH__TOKEN", "")),
    )
    args = parser.parse_args()

    configure_logging(service="cortex-presence", environment="prod", level="INFO")
    asyncio.run(_serve(args))


async def _serve(args: argparse.Namespace) -> None:
    bus = NatsEventBus(config=NatsEventBusConfig(servers=(args.nats_url,), name="cortex-presence"))
    await bus.connect()
    client = httpx.AsyncClient(timeout=5.0)

    params = {"token": args.token} if args.token else None

    async def frames() -> bytes | None:
        try:
            response = await client.get(args.snapshot_url, params=params)
        except httpx.HTTPError:
            return None
        if response.status_code != httpx.codes.OK:
            return None
        return response.content

    runner = PresenceRunner(
        bus=bus,
        frames=frames,
        threshold=args.threshold,
        interval_s=args.interval_s,
        rearm_s=args.rearm_s,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_stop)
    try:
        await runner.run()
    finally:
        await client.aclose()
        await bus.close()


if __name__ == "__main__":
    main()
