"""One JSON line per log record, with what the request in hand bound to it.

The API logged `LEVEL: name: message`, with the data inside the message and a
traceback spread over as many lines as it has frames. A shipper cannot tell the
lines of one failure from the next, and nothing tied a line to a request. This
is the stdlib's answer, without a dependency: a formatter, and a context that
follows the request through `await`s.
"""

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


@contextmanager
def bound(**fields: Any) -> Generator[None]:
    """Everything logged inside carries these fields."""
    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    """The record as one line: `event`, `level`, `logger`, the bound context, `fields`.

    `fields` is what a call passes as `extra={"fields": {...}}`: values to
    search on, kept out of the message so the message stays one event name.
    """

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "event": record.getMessage(),
            "logger": record.name,
            "level": record.levelname.lower(),
            "severity": record.levelname,
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="microseconds"
            ),
            **(_context.get() or {}),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)
