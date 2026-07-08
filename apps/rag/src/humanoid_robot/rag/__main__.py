"""cortex-rag CLI entrypoint."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import typer

from humanoid_robot.observability import configure_logging, get_logger
from humanoid_robot.rag.composition import RagComposition
from humanoid_robot.rag.grounded_qa import (
    GroundedQAConfig,
    GroundedQAOrchestrator,
)
from humanoid_robot.rag.runner import RagRunner
from humanoid_robot.rag.settings import RagRunnerSettings, load_settings

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("info")
def info() -> None:
    """Print RAG orchestrator status without starting any I/O."""
    configure_logging(service="cortex-rag", environment="dev", level="INFO")
    log = get_logger("cortex-rag")
    log.info("cortex-rag.info", version="0.0.0")


@cli.command("run")
def run(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        readable=True,
        help="YAML config file (see deploy/config/rag.yaml).",
    ),
) -> None:
    """Compose adapters and consume asr.final events until SIGTERM/SIGINT."""

    settings = load_settings(config_path=config)
    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.log_level,
    )
    asyncio.run(_serve(settings))


async def _serve(settings: RagRunnerSettings) -> None:
    log = get_logger("cortex-rag.runner")
    composition = await RagComposition.build(settings)
    orch = GroundedQAOrchestrator(
        vector_store=composition.vector_store,
        reranker=composition.reranker,
        llm=composition.llm,
        config=GroundedQAConfig(
            top_k_retrieve=composition.settings.qa.top_k_retrieve,
            top_k_after_rerank=composition.settings.qa.top_k_after_rerank,
            min_top1_rerank_score=composition.settings.qa.min_top1_rerank_score,
            min_chunk_coverage=composition.settings.qa.min_chunk_coverage,
            max_answer_tokens=composition.settings.qa.max_answer_tokens,
            max_retries_on_citation_fail=composition.settings.qa.max_retries_on_citation_fail,
        ),
    )
    runner = RagRunner(
        orchestrator=orch,
        bus=composition.bus,
        producer=composition.settings.service_name,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_stop)
    log.info("cortex-rag.run")
    try:
        await runner.run()
    finally:
        await composition.bus.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
