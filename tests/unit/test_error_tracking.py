"""Errors reach Sentry by name, and nothing secret or personal goes with them."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
import sentry_sdk
import structlog
from app.core import error_tracking
from app.core.config import settings
from app.core.logging import setup_logging
from pydantic import SecretStr
from sentry_sdk.transport import Transport

if TYPE_CHECKING:
    from collections.abc import Iterator

_TOKEN = "123456789:AAH" + "x" * 32


class Captured(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry(monkeypatch) -> Iterator[Captured]:
    monkeypatch.setattr(settings.sentry, "dsn", SecretStr("https://key@o0.ingest.sentry.io/0"))
    # The suite logs at ERROR; warnings are part of what is tested here.
    monkeypatch.setattr(settings.logging, "level", "INFO")
    setup_logging()
    assert error_tracking.setup_error_tracking("bot")
    transport = Captured()
    sentry_sdk.get_client().transport = transport
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.init(dsn=None)
    for name in ("", *error_tracking.WATCHED_LOGGERS):
        for handler in [h for h in logging.getLogger(name).handlers if isinstance(h, error_tracking.SentryLogHandler)]:
            logging.getLogger(name).removeHandler(handler)
    monkeypatch.undo()
    setup_logging()


def _text(events: list[dict]) -> str:
    return repr(events)


def test_off_without_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(settings.sentry, "dsn", SecretStr(""))

    assert error_tracking.setup_error_tracking("bot") is False


def test_an_error_is_sent_by_its_event_name_not_its_line(sentry: Captured) -> None:
    with structlog.contextvars.bound_contextvars(update_id=7, chat_id=-100):
        structlog.get_logger("captcha").error("intro_failed", text="Привет, мой номер +420 777 123 456")

    assert len(sentry.events) == 1
    event = sentry.events[0]
    assert event["message"] == "intro_failed"
    assert event["tags"]["update_id"] == "7"
    assert "Привет" not in _text(sentry.events)
    assert "777" not in _text(sentry.events)


def test_a_logged_exception_keeps_its_traceback(sentry: Captured) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        structlog.get_logger("x").error("update_failed", exc_info=True)

    [event] = sentry.events
    assert event["exception"]["values"][-1]["type"] == "ValueError"
    assert event["extra"]["log_event"] == "update_failed"


def test_warnings_are_breadcrumbs_not_events(sentry: Captured) -> None:
    structlog.get_logger("chats.metadata").warning("get_chat_failed", error="bot was kicked")
    structlog.get_logger("x").error("later_failure")

    [event] = sentry.events
    crumbs = [c["message"] for c in event["breadcrumbs"]["values"]]
    assert "get_chat_failed" in crumbs
    assert "bot was kicked" not in _text(sentry.events)


def test_retried_polling_failures_are_not_sent(sentry: Captured) -> None:
    logging.getLogger("aiogram.dispatcher").error("Failed to fetch updates - %s: %s", "TelegramServerError", "502")

    assert sentry.events == []


@pytest.mark.parametrize(
    ("value", "secret"),
    [
        (f"https://api.telegram.org/bot{_TOKEN}/getUpdates", _TOKEN),
        ("tma query_id=AA&user=%7B%7D&auth_date=1&hash=abc", "query_id=AA"),
        ("Bearer eyJhbGciOi.payload.sig", "eyJhbGciOi"),
        ("https://konnekt.cz/#tgWebAppData=user%3D1%26hash%3Dff", "user%3D1"),
        ("call +420 777 123 456 now", "777 123"),
    ],
)
def test_secrets_in_any_value_are_filtered(value: str, secret: str) -> None:
    event: Any = {"extra": {"anything": value}, "breadcrumbs": {"values": [{"data": {"url": value}}]}}
    scrubbed = error_tracking._before_send(event, {})

    assert secret not in repr(scrubbed)


def test_ids_survive_scrubbing() -> None:
    event: Any = {"tags": {"chat_id": "-1004313465922", "update_id": "745020106"}}

    assert error_tracking._before_send(event, {}) == event
