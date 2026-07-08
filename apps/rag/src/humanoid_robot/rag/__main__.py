"""cortex-rag CLI entrypoint (stub — real runner lands next round)."""

from __future__ import annotations

import typer

from humanoid_robot.observability import configure_logging, get_logger

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("info")
def info() -> None:
    """Print RAG orchestrator status without starting any I/O."""
    configure_logging(service="cortex-rag", environment="dev", level="INFO")
    log = get_logger("cortex-rag")
    log.info(
        "cortex-rag.info",
        note="grounded QA orchestrator implemented; NATS runner arrives in round 2",
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
