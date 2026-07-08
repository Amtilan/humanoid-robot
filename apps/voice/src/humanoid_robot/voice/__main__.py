"""cortex-voice CLI entrypoint (skeleton).

At Phase 3 round 1, the runner wires up the session with real adapters only
if their runtime dependencies are installed. In the meantime this command
prints the configuration it would use and exits.
"""

from __future__ import annotations

import typer

from humanoid_robot.observability import configure_logging, get_logger

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("info")
def info() -> None:
    """Print voice-orchestrator status without starting any I/O."""
    configure_logging(service="cortex-voice", environment="dev", level="INFO")
    log = get_logger("cortex-voice")
    log.info("cortex-voice.info", note="stub — full runner lands in Phase 3 round 2")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
