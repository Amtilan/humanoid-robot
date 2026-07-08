"""cortex-ingest CLI entrypoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from humanoid_robot.ingest.composition import IngestComposition
from humanoid_robot.ingest.orchestrator import IngestOrchestrator
from humanoid_robot.ingest.settings import load_settings
from humanoid_robot.observability import configure_logging, get_logger

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("info")
def info() -> None:
    """Print ingest status without starting any I/O."""
    configure_logging(service="cortex-ingest", environment="dev", level="INFO")
    log = get_logger("cortex-ingest")
    log.info("cortex-ingest.info", version="0.0.0")


@cli.command("run")
def run(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        readable=True,
        help="YAML config file (see deploy/config/ingest.yaml).",
    ),
    directory: Path = typer.Option(
        ...,
        "--dir",
        exists=True,
        readable=True,
        help="Root directory to ingest (file or dir).",
    ),
) -> None:
    """Parse every file under `--dir`, chunk, embed, upsert."""

    settings = load_settings(config_path=config)
    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.log_level,
    )
    asyncio.run(_serve(settings, directory))


async def _serve(settings: object, directory: Path) -> None:
    log = get_logger("cortex-ingest.runner")
    composition = IngestComposition.build(settings)  # type: ignore[arg-type]
    orchestrator = IngestOrchestrator(
        parsers=composition.parsers,
        chunker=composition.chunker,
        vector_store=composition.vector_store,
        chunk_batch_size=composition.settings.chunk_batch_size,
    )
    report = await orchestrator.ingest_path(directory)
    log.info(
        "cortex-ingest.done",
        ok=report.ok_files,
        failed=report.failed_files,
        chunks=report.total_chunks,
    )
    await composition.vector_store.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
