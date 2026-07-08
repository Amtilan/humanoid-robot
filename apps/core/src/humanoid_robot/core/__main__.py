"""Console entrypoint — starts uvicorn against the FastAPI app."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from humanoid_robot.core.app import create_app
from humanoid_robot.core.settings import load_settings

cli = typer.Typer(add_completion=False, no_args_is_help=False)


@cli.command()
def serve(
    config: Path | None = typer.Option(
        None,
        "--config",
        exists=True,
        readable=True,
        help="Optional YAML config file.",
    ),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
) -> None:
    """Run the FastAPI orchestrator with uvicorn."""

    settings = load_settings(config_path=config)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host or settings.http.host,
        port=port or settings.http.port,
        log_config=None,  # our structlog handler already owns stdlib logging
        access_log=False,
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
