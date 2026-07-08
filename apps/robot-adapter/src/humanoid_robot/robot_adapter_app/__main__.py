"""cortex-robot-adapter — CLI entrypoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from humanoid_robot.observability import configure_logging
from humanoid_robot.plugins_sdk import AdapterRegistry
from humanoid_robot.robot_adapter_app.runner import run_until_signal
from humanoid_robot.robot_adapter_app.settings import load_settings

cli = typer.Typer(add_completion=False, no_args_is_help=True)


@cli.command("list")
def list_adapters() -> None:
    """Print discovered adapter names, versions, and distributions."""

    registry = AdapterRegistry.discover()
    if not registry.names():
        typer.echo("no adapters registered")
        raise typer.Exit(code=1)
    for name in registry.names():
        entry = registry.get(name)
        typer.echo(f"{name}\tdist={entry.distribution or '?'}\tversion={entry.version or '?'}")


@cli.command("run")
def run(
    adapter: str = typer.Argument(..., help="Adapter name (see `list`)."),
    config: Path | None = typer.Option(
        None,
        "--config",
        exists=True,
        readable=True,
        help="Optional YAML config file.",
    ),
    interface: str | None = typer.Option(
        None, "--interface", help="Network interface (adapter kwarg)."
    ),
    mic_source: str | None = typer.Option(None, "--mic-source", help='"g1" | "alsa" | "r1".'),
    nats_server: str | None = typer.Option(None, "--nats", help="Override NATS URL."),
) -> None:
    """Load one adapter and keep it running until SIGTERM."""

    settings = load_settings(config_path=config)
    settings.adapter_name = adapter
    if interface is not None:
        settings.adapter_config = {**settings.adapter_config, "network_interface": interface}
    if mic_source is not None:
        settings.adapter_config = {**settings.adapter_config, "mic_source": mic_source}
    if nats_server is not None:
        settings.nats = settings.nats.model_copy(update={"servers": (nats_server,)})
    configure_logging(
        service=settings.service_name,
        environment=settings.environment,
        level=settings.log_level,
    )
    asyncio.run(run_until_signal(settings))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
