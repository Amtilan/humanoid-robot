"""CLI entrypoint: ``cortex-wall-agent --driver sim --port 8093``."""

from __future__ import annotations

import argparse
import logging
import os

from humanoid_robot.wall_agent.drivers import build_driver
from humanoid_robot.wall_agent.server import serve

log = logging.getLogger("humanoid_robot.wall_agent")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cortex-wall-agent",
        description="HTTP control agent for the presentation video wall.",
    )
    parser.add_argument(
        "--driver",
        choices=["sim", "sendinput"],
        default="sim",
        help="sim = in-memory simulator; sendinput = Windows input emulation",
    )
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument(
        "--token",
        default=os.environ.get("HR_WALL_AGENT_TOKEN", ""),
        help="shared secret; clients send it as X-Wall-Token",
    )
    parser.add_argument(
        "--mapping",
        default=None,
        help="path to the click/key mapping JSON (sendinput driver)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    driver = build_driver(args.driver, mapping_path=args.mapping)
    server = serve(driver, host=args.host, port=args.port, token=args.token)
    log.info(
        "wall agent listening on %s:%d (driver=%s, auth=%s)",
        args.host,
        args.port,
        driver.name,
        "on" if args.token else "off",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        log.info("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
