"""cortex-rag CLI entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path

import typer

from humanoid_robot.observability import configure_logging, get_logger
from humanoid_robot.rag.composition import RagComposition
from humanoid_robot.rag.conversation import ConversationConfig, ConversationOrchestrator
from humanoid_robot.rag.grounded_qa import (
    GroundedQAConfig,
    GroundedQAOrchestrator,
)
from humanoid_robot.rag.llm_config_sync import LlmConfigSync
from humanoid_robot.rag.runner import QaOrchestrator, RagRunner
from humanoid_robot.rag.settings import RagRunnerSettings, load_settings


def _build_orchestrator(composition: RagComposition) -> QaOrchestrator:
    """Pick the conversational or grounded orchestrator from settings.mode."""
    s = composition.settings
    if s.mode == "conversation":
        # Only override the persona prompts when configured; otherwise keep the
        # ConversationConfig code defaults (the "Слуга" robot persona).
        prompt_overrides = {
            k: v
            for k, v in (
                ("system_prompt_ru", s.conversation.system_prompt_ru),
                ("system_prompt_en", s.conversation.system_prompt_en),
            )
            if v
        }
        return ConversationOrchestrator(
            vector_store=composition.vector_store,
            reranker=composition.reranker,
            llm=composition.llm,
            config=ConversationConfig(
                retrieve=s.conversation.retrieve,
                top_k_retrieve=s.conversation.top_k_retrieve,
                top_k_context=s.conversation.top_k_context,
                min_context_score=s.conversation.min_context_score,
                temperature=s.conversation.temperature,
                max_tokens=s.conversation.max_tokens,
                **prompt_overrides,
            ),
        )
    return GroundedQAOrchestrator(
        vector_store=composition.vector_store,
        reranker=composition.reranker,
        llm=composition.llm,
        config=GroundedQAConfig(
            top_k_retrieve=s.qa.top_k_retrieve,
            top_k_after_rerank=s.qa.top_k_after_rerank,
            min_top1_rerank_score=s.qa.min_top1_rerank_score,
            min_chunk_coverage=s.qa.min_chunk_coverage,
            max_answer_tokens=s.qa.max_answer_tokens,
            max_retries_on_citation_fail=s.qa.max_retries_on_citation_fail,
        ),
    )


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
    orch = _build_orchestrator(composition)
    log.info("cortex-rag.mode", mode=composition.settings.mode)
    runner = RagRunner(
        orchestrator=orch,
        bus=composition.bus,
        producer=composition.settings.service_name,
    )
    # Live local⇄cloud LLM switching from the app; the yaml values are the
    # local baseline to fall back to.
    llm_sync = LlmConfigSync(
        composition.llm,
        local_base_url=settings.stack.llm.config.get("base_url", "http://llama-cpp:8080"),
        local_model=settings.stack.llm.config.get("model", ""),
    )
    llm_sync_sub = await llm_sync.start(composition.bus)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_stop)
    log.info("cortex-rag.run")
    try:
        await runner.run()
    finally:
        with contextlib.suppress(Exception):
            await llm_sync_sub.cancel()
        await composition.bus.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
