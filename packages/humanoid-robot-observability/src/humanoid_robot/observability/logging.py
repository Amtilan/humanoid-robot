"""structlog configuration used by every process.

Rules:
    - JSON output (never printable strings) — logs are parsed by Loki.
    - Timestamps are ISO-8601 UTC.
    - Every log event carries `service`, `environment`, and the
      correlation-id contextvar if bound.
    - `logging.getLogger(...)` from stdlib is bridged into structlog so that
      third-party libraries also emit JSON.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.stdlib import BoundLogger

from humanoid_robot.observability.context import current_context


def _inject_context(
    _logger: Any,  # noqa: ANN401
    _name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    for k, v in current_context().items():
        event_dict.setdefault(k, v)
    return event_dict


def configure_logging(
    *,
    service: str,
    environment: str = "prod",
    level: str = "INFO",
) -> None:
    """Configure structlog + stdlib logging into a unified JSON pipeline."""
    processors: list[structlog.typing.Processor] = [
        merge_contextvars,
        _inject_context,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        structlog.processors.dict_tracebacks,
    ]

    # Unified pipeline (structlog → ProcessorFormatter → stdlib handler).
    # structlog produces a partially-processed record; `ProcessorFormatter`
    # finishes the pipeline in stdlib logging so third-party stdlib loggers
    # go through the exact same processors.
    structlog.configure(
        processors=[
            *processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    stdlib_handler = logging.StreamHandler(stream=sys.stdout)
    stdlib_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.EventRenamer("message"),
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [stdlib_handler]
    root.setLevel(level.upper())

    # Default context bound to every log record.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service, environment=environment)


def get_logger(name: str) -> BoundLogger:
    """Return a structlog `BoundLogger` for the given module name."""
    return structlog.stdlib.get_logger(name)
