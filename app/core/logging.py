"""Structured logging configuration."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def add_severity_level(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Add severity level to log event."""
    event_dict["severity"] = event_dict.get("level", "info").upper()
    return event_dict


def add_timestamp(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Add timestamp to log event."""
    return event_dict


def _keep_event_name(renderer: Processor) -> Processor:
    """Render as before, and carry the bare event name on the stdlib record.

    The error alerts send that name and nothing else; without it they would
    have to pick it out of a rendered line, which is where the data is.
    """

    def render(logger: Any, method_name: str, event_dict: EventDict) -> Any:
        event = str(event_dict.get("event", "?"))
        return (renderer(logger, method_name, event_dict),), {"extra": {"structlog_event": event}}

    return render


def setup_logging() -> None:
    """Setup structured logging with both console and file output."""

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.logging.level.upper(), logging.INFO),
    )

    # Setup file logging if path is provided
    if settings.logging.file_path:
        log_file = Path(settings.logging.file_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=settings.logging.max_bytes,
            backupCount=settings.logging.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, settings.logging.level.upper(), logging.INFO))

        # Add file handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

    # Configure processors based on environment
    processors: list[Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        add_severity_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Use JSON formatter in production, colored console in development
    if settings.environment == "production":
        processors.append(_keep_event_name(structlog.processors.JSONRenderer()))
    else:
        processors.append(_keep_event_name(structlog.dev.ConsoleRenderer(colors=True)))

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a configured logger instance."""
    return structlog.get_logger(name)
