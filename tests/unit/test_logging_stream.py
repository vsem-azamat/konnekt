"""Every record leaves the process as one line a log shipper can parse.

aiogram, uvicorn and SQLAlchemy log through the standard library, and their
lines used to leave as bare text: a traceback became one Loki entry per line,
and the level was nowhere in the line at all.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TYPE_CHECKING

import structlog
from app.core.logging import ForeignRecordFormatter, get_logger, setup_logging

if TYPE_CHECKING:
    import pytest


def _record(msg: str, *args: object, exc_info: object = None, name: str = "aiogram.event") -> logging.LogRecord:
    return logging.LogRecord(name, logging.ERROR, __file__, 1, msg, args or None, exc_info)  # ty: ignore[invalid-argument-type]


def test_a_foreign_record_becomes_one_json_line() -> None:
    line = ForeignRecordFormatter(json_output=True).format(_record("Update id=%s is not handled", 7))

    parsed = json.loads(line)
    assert "\n" not in line
    assert parsed["event"] == "Update id=7 is not handled"
    assert parsed["logger"] == "aiogram.event"
    assert parsed["level"] == "error"
    assert parsed["severity"] == "ERROR"
    assert parsed["timestamp"]


def test_its_traceback_stays_inside_the_same_line() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record("Cause exception while process update", exc_info=sys.exc_info())

    line = ForeignRecordFormatter(json_output=True).format(record)

    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["exception"]


def test_a_structlog_line_passes_through_untouched() -> None:
    record = _record('{"event": "kick_failed", "chat_id": 1}')
    record.structlog_event = "kick_failed"

    assert ForeignRecordFormatter(json_output=True).format(record) == '{"event": "kick_failed", "chat_id": 1}'


def test_development_reads_as_text() -> None:
    line = ForeignRecordFormatter(json_output=False).format(_record("hello"))

    assert "hello" in line
    assert "aiogram.event" in line
    assert "ERROR" in line


def test_setup_puts_the_formatter_on_every_way_out(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings.logging, "file_path", str(tmp_path / "bot.log"))
    uvicorn_handler = logging.StreamHandler()
    logging.getLogger("uvicorn.error").addHandler(uvicorn_handler)
    try:
        setup_logging()
        setup_logging()  # idempotent: the second call must not double every line

        root = logging.getLogger()
        ours = [h for h in root.handlers if isinstance(h.formatter, ForeignRecordFormatter)]
        assert len(ours) == 2  # stdout and the file
        assert isinstance(uvicorn_handler.formatter, ForeignRecordFormatter)
    finally:
        logging.getLogger("uvicorn.error").removeHandler(uvicorn_handler)
        for handler in [h for h in logging.getLogger().handlers if isinstance(h.formatter, ForeignRecordFormatter)]:
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_httpx_does_not_log_every_request_url() -> None:
    setup_logging()

    assert logging.getLogger("httpx").level >= logging.WARNING


def test_context_bound_once_reaches_every_line_ours_or_a_librarys() -> None:
    """Through the configured pipeline and out of a real handler, not capture_logs' own merge."""
    setup_logging()
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(self.format(record))

    capture = Capture()
    capture.setFormatter(ForeignRecordFormatter(json_output=True))
    root = logging.getLogger()
    root.addHandler(capture)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(update_id=42)
    try:
        # structlog's own lines are rendered by its chain, which merges the context...
        get_logger("t").error("ours")
        # ...a library's by the formatter.
        logging.getLogger("aiogram.event").error("theirs")
    finally:
        structlog.contextvars.clear_contextvars()
        root.removeHandler(capture)

    ours, theirs = seen
    assert "update_id" in ours
    assert json.loads(theirs)["update_id"] == 42


def test_timestamps_are_spelled_as_structlogs() -> None:
    line = ForeignRecordFormatter(json_output=True).format(_record("x"))

    assert json.loads(line)["timestamp"].endswith("Z")


def test_a_stack_asked_for_is_not_dropped() -> None:
    record = _record("where am I")
    record.stack_info = "Stack (most recent call last):\n  File x"

    assert "File x" in json.loads(ForeignRecordFormatter(json_output=True).format(record))["stack"]
