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
from humanoid_robot.rag.guard_kb import GuardKb
from humanoid_robot.rag.llm_config_sync import LlmConfigSync
from humanoid_robot.rag.presenter_kb import PRESENTER_SYSTEM_PROMPT_RU, PresenterKb
from humanoid_robot.rag.runner import QaOrchestrator, RagRunner
from humanoid_robot.rag.settings import RagRunnerSettings, load_settings
from humanoid_robot.rag.wall_intent import WallIntentMatcher


def _load_guard_kb(s: RagRunnerSettings) -> GuardKb | None:
    """Customer reference data, only in guard mode."""
    if not s.guard.intake_enabled:
        return None
    return GuardKb.load(s.guard.kb_path)


def _build_orchestrator(
    composition: RagComposition,
    kb: GuardKb | None,
    presenter_kb: PresenterKb | None = None,
) -> QaOrchestrator:
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
        if kb is not None and not kb.empty:
            # The customer's справка rides inside the persona so the LLM
            # consults ONLY approved materials.
            base_ru = prompt_overrides.get(
                "system_prompt_ru", ConversationConfig().system_prompt_ru
            )
            prompt_overrides["system_prompt_ru"] = base_ru + "\n" + kb.reference_block()
        if presenter_kb is not None:
            # Presenter scenario (plan §6): persona + allowed/forbidden topics
            # + the project справка as the only source of facts. An explicit
            # yaml override still wins.
            base_ru = s.conversation.system_prompt_ru or PRESENTER_SYSTEM_PROMPT_RU
            prompt_overrides["system_prompt_ru"] = base_ru + presenter_kb.reference_block()
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
    guard_kb = _load_guard_kb(settings)
    wall_intent = None
    presenter_kb = None
    if settings.wall.enabled:
        wall_intent = WallIntentMatcher(config_path=settings.wall.config_path)
        presenter_kb = PresenterKb.load(settings.wall.kb_path, matcher=wall_intent)
        if presenter_kb.empty:
            presenter_kb = None
        log.info(
            "wall_intent.enabled",
            config_path=settings.wall.config_path,
            kb_path=settings.wall.kb_path,
            kb_sections=0 if presenter_kb is None else len(presenter_kb.sections),
        )
    orch = _build_orchestrator(composition, guard_kb, presenter_kb)
    log.info("cortex-rag.mode", mode=composition.settings.mode)
    runner = RagRunner(
        orchestrator=orch,
        bus=composition.bus,
        producer=composition.settings.service_name,
        guard_intake_enabled=composition.settings.guard.intake_enabled,
        guard_kb=guard_kb,
        wall_intent=wall_intent,
        presenter_kb=presenter_kb,
        greeting_text=(
            settings.wall.greeting_ru
            if settings.wall.enabled and settings.wall.greeting_enabled
            else ""
        ),
        greeting_cooldown_s=settings.wall.greeting_cooldown_s,
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
