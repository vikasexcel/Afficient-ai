"""Centralised structlog configuration.

Call ``configure_logging()`` once on application startup. Use ``get_logger(name)``
anywhere in the codebase to obtain a structured, bound logger.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from config.settings import settings


def _level() -> int:
    return getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=_level(),
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.LOG_JSON or settings.ENV != "development":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(_level()),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
