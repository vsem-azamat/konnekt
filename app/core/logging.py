"""Structured logging configuration."""

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def add_severity_level(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Add severity level to log event."""
    event_dict["severity"] = event_dict.get("level", "info").upper()
    return event_dict


def _keep_event_name(renderer: Processor) -> Processor:
    """Render as before, and carry the bare event name on the stdlib record.

    The error alerts send that name and nothing else; without it they would
    have to pick it out of a rendered line, which is where the data is.
    """

    def render(logger: Any, method_name: str, event_dict: EventDict) -> Any:
        event = str(event_dict.pop(_EVENT_NAME, "?"))
        return (renderer(logger, method_name, event_dict),), {"extra": {"structlog_event": event}}

    return render


_EVENT_NAME = "_event_name"


def _remember_event_name(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """The event as written, before positional arguments are formatted into it."""
    event_dict[_EVENT_NAME] = event_dict.get("event", "?")
    return event_dict


class QuietHealthChecks(logging.Filter):
    """Drop the container healthcheck's requests from uvicorn's access log.

    It asks every 30 s for as long as the container runs, and the lines it
    leaves push real requests out of the rotated log within days.
    """

    PATHS = ("/api/health",)

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        path = str(args[2]).split("?", 1)[0] if len(args) > 2 else ""
        return path not in self.PATHS


class ForeignRecordFormatter(logging.Formatter):
    """Give records that did not come from structlog the shape of those that did.

    aiogram, uvicorn, SQLAlchemy and httpx log through the standard library.
    Their lines left as bare text: the level was nowhere in them, and a
    traceback became one log entry per line. Our own lines are already rendered
    and are passed through as they are.
    """

    def __init__(self, *, json_output: bool) -> None:
        super().__init__()
        self.json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "structlog_event"):
            return record.getMessage()
        level = record.levelname.lower()
        event = record.getMessage()
        exception = self.formatException(record.exc_info) if record.exc_info else None
        # The same spelling structlog's TimeStamper writes, so one query reads both.
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="microseconds")
        timestamp = timestamp.replace("+00:00", "Z")
        # What the update or request in hand bound: a library's line is as much
        # part of it as ours.
        context = structlog.contextvars.get_contextvars()
        if not self.json_output:
            text = f"{timestamp} [{record.levelname}] {record.name}: {event}"
            if context:
                text += " " + " ".join(f"{key}={value}" for key, value in context.items())
            for extra in (exception, record.stack_info):
                if extra:
                    text += f"\n{extra}"
            return text
        fields: dict[str, object] = {
            "event": event,
            "logger": record.name,
            "level": level,
            "severity": record.levelname,
            "timestamp": timestamp,
            **context,
        }
        if exception:
            fields["exception"] = exception
        if record.stack_info:
            fields["stack"] = record.stack_info
        return json.dumps(fields, ensure_ascii=False, default=str)


_OURS = "_konnekt_handler"

# Their own handlers and formatters; ours replaces only the formatter.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# At INFO it writes every request URL it makes, once per call.
_QUIET_LIBRARIES = ("httpx", "httpcore")


def _install(root: logging.Logger, handler: logging.Handler) -> None:
    """Replace this module's earlier handler of the same kind, so a second call adds nothing."""
    for old in [h for h in root.handlers if getattr(h, _OURS, None) == type(handler).__name__]:
        root.removeHandler(old)
        old.close()
    setattr(handler, _OURS, type(handler).__name__)
    root.addHandler(handler)


def setup_logging() -> None:
    """Setup structured logging with both console and file output."""

    level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    formatter = ForeignRecordFormatter(json_output=settings.environment == "production")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    _install(root_logger, console)

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
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        _install(root_logger, file_handler)

    # uvicorn configured its own loggers before this module was imported, and
    # they do not reach the root handler.
    for name in _UVICORN_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)
    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Configure processors based on environment
    processors: list[Processor] = [
        _remember_event_name,
        # Whatever a middleware bound for the update or request in hand.
        structlog.contextvars.merge_contextvars,
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
        # No colour codes when a log file shares the rendered line.
        colors = not settings.logging.file_path
        processors.append(_keep_event_name(structlog.dev.ConsoleRenderer(colors=colors)))

    logging.getLogger("uvicorn.access").addFilter(QuietHealthChecks())

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
