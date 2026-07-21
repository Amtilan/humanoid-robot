"""cortex-voice CLI entrypoint."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import typer

from humanoid_robot.observability import configure_logging, get_logger
from humanoid_robot.voice.asr_config_sync import AsrConfigSync
from humanoid_robot.voice.cloud_asr import SwitchableAsr
from humanoid_robot.voice.composition import VoiceComposition
from humanoid_robot.voice.runner import VoiceRunner
from humanoid_robot.voice.session import VoiceSessionConfig
from humanoid_robot.voice.settings import load_settings

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("info")
def info() -> None:
    """Print voice-orchestrator status without starting any I/O."""
    configure_logging(service="cortex-voice", environment="dev", level="INFO")
    log = get_logger("cortex-voice")
    log.info("cortex-voice.info", version="0.0.0")


@cli.command("run")
def run(
    config: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        readable=True,
        help="YAML config file (see deploy/config/voice.yaml).",
    ),
) -> None:
    """Compose adapters and run the voice pipeline until SIGTERM/SIGINT."""

    settings = load_settings(config_path=config)
    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.log_level,
    )
    asyncio.run(_serve(settings))


async def _serve(settings: object) -> None:
    log = get_logger("cortex-voice.runner")
    composition = await VoiceComposition.build(settings)  # type: ignore[arg-type]
    session_cfg = VoiceSessionConfig(
        language_hint=composition.session_language(),
        min_speech_ms=composition.settings.session.min_speech_ms,
        silence_hang_ms=composition.settings.session.silence_hang_ms,
        max_utterance_ms=composition.settings.session.max_utterance_ms,
        require_wake_word=composition.settings.session.require_wake_word,
        wake_word_grace_ms=composition.settings.session.wake_word_grace_ms,
        wake_name=composition.settings.session.wake_name,
        wake_name_mode=composition.settings.session.wake_name_mode,
        producer=composition.settings.service_name,
    )
    # Cloud transcription rides the same app-configured token as the LLM;
    # local whisper remains the fallback for every utterance.
    asr = SwitchableAsr(composition.asr)
    asr_sync = AsrConfigSync(asr)
    asr_sync_sub = await asr_sync.start(composition.bus)
    runner = VoiceRunner(
        audio_in=composition.audio_in,
        audio_out=composition.audio_out,
        vad=composition.vad,
        asr=asr,
        tts=composition.tts,
        bus=composition.bus,
        wake_word=composition.wake_word,
        config=session_cfg,
        speak_all=composition.settings.session.speak_all_answers,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner.request_stop)
    log.info("voice_cli.run", session_id=runner.session_id)
    try:
        await runner.run()
    finally:
        await asr_sync_sub.cancel()
        await composition.bus.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
