"""Errors reach Sentry by name, and nothing secret or personal goes with them."""

from __future__ import annotations

import logging
import time
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
    # The whole number: bare «777» turns up in a timestamp or a random event id.
    assert "777 123 456" not in _text(sentry.events)


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


def test_a_request_keeps_its_route_not_the_ids_or_query_in_it() -> None:
    event: Any = {
        "request": {
            "method": "GET",
            "url": "https://konnekt.cz/api/audience/555777999?q=Ivan+Petrov",
            "query_string": "q=Ivan+Petrov",
            "headers": {"Referer": "https://konnekt.cz/#tgWebAppData=x"},
            "data": {"text": "Привет"},
        }
    }

    scrubbed: Any = error_tracking._before_send(event, {})
    request = scrubbed["request"]

    assert request == {"method": "GET", "url": "https://konnekt.cz/api/audience/:id"}


def test_an_outgoing_call_loses_its_query_and_ids() -> None:
    crumb: Any = {
        "category": "httplib",
        "data": {"url": "http://catalog-api:8000/api/v1/admin/profiles/555777999", "http.query": "phone=777123456"},
    }

    scrubbed: Any = error_tracking._before_breadcrumb(crumb, {})

    assert scrubbed["data"] == {"url": "http://catalog-api:8000/api/v1/admin/profiles/:id"}


def test_a_database_error_loses_the_values_it_quotes() -> None:
    event: Any = {"exception": {"values": [{"value": "DETAIL:  Key (tg_id)=(555777999) already exists."}]}}

    scrubbed: Any = error_tracking._before_send(event, {})
    value = scrubbed["exception"]["values"][0]["value"]

    assert "555777999" not in value
    assert value.startswith("DETAIL:")


def test_the_events_own_ids_are_kept() -> None:
    sha = "0064152123456aa7711d0000000000000000abcd"
    event: Any = {"release": sha, "event_id": "1234567890abcdef1234567890abcdef"}

    assert error_tracking._before_send(event, {}) == event


def test_an_uvicorn_error_is_one_event_though_two_loggers_carry_it(sentry: Captured) -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    propagates = uvicorn_error.propagate
    uvicorn_error.propagate = True
    try:
        uvicorn_error.error("Application startup failed. Exiting.")
    finally:
        uvicorn_error.propagate = propagates

    assert len(sentry.events) == 1


async def test_a_deliberate_503_is_not_an_issue(sentry: Captured) -> None:
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()

    @app.get("/down")
    async def down() -> None:
        raise HTTPException(503, "catalog not connected")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/down")).status_code == 503

    assert sentry.events == []


def test_a_transaction_is_scrubbed_like_an_error(sentry: Captured) -> None:
    """Traced requests skip before_send; a span names every URL called, the bot's token in it."""
    event: Any = {"spans": [{"description": f"POST https://api.telegram.org/bot{_TOKEN}/sendMessage"}]}

    hook = sentry_sdk.get_client().options["before_send_transaction"]

    assert _TOKEN not in repr(hook(event, {}))


@pytest.mark.parametrize(
    ("text", "personal"),
    [
        (
            'null value in column "x" violates not-null constraint\nDETAIL:  Failing row contains (17, Ahoj, ivan@example.cz).',
            "ivan@example.cz",
        ),
        ("1 validation error\n  Value error [type=value_error, input_value='my name is Ivan', input_type=str]", "Ivan"),
        ("{'type': 'missing', 'loc': ('body',), 'msg': 'Field required', 'input': {'text': 'Ivan'}}", "Ivan"),
        (
            "violates not-null constraint\nDETAIL:  Failing row contains (1, Ahoj\nIvan 2nd line, null).\n[SQL: INSERT]",
            "Ivan",
        ),
        ("DETAIL:  Key (body)=(Ahoj\nIvan) already exists.", "Ivan"),
        ("Value error [type=value_error, input_value={'a': [1], 'name': 'Ivan'}, input_type=dict]", "Ivan"),
        ("Value error [type=value_error, input_value=['x]', 'Ivan'], input_type=list]", "Ivan"),
        ("  {'type': 'dict_type', 'loc': ('response',), 'input': {'a': {}, 'bio': 'Ivan'}}", "Ivan"),
        ("  {'type': 'list_type', 'loc': ('response',), 'input': ['x', 'Ivan']}", "Ivan"),
        ("DETAIL:  Failing row contains (1, a\nHINT: b Ivan, null).\n[SQL: INSERT]", "Ivan"),
        ("Value error [type=value_error, input_value='a, input_type=b Ivan', input_type=str]", "Ivan"),
    ],
)
def test_errors_that_quote_their_input_lose_it(text: str, personal: str) -> None:
    event: Any = {"exception": {"values": [{"value": text}]}}

    assert personal not in repr(error_tracking._before_send(event, {}))


def test_a_request_is_named_by_its_route_when_the_route_is_known() -> None:
    event: Any = {
        "transaction": "/api/public/avatars/{file_id}",
        "transaction_info": {"source": "route"},
        "request": {"method": "GET", "url": "https://konnekt.cz/api/public/avatars/AgADx7"},
    }

    scrubbed: Any = error_tracking._before_send(event, {})

    assert scrubbed["request"]["url"] == "https://konnekt.cz/api/public/avatars/{file_id}"


def test_a_long_value_is_scrubbed_in_good_time() -> None:
    """One pattern took seconds on a long run of non-space characters, on the event loop."""
    event: Any = {
        "extra": {
            "blob": "a" * 400_000,
            "digits": "1" * 400_000,
            "schemes": "a://" * 100_000,
            "url": "https://x/?" + "auth_date=1&" * 20_000 + "hash=f",
        }
    }
    started = time.perf_counter()

    scrubbed: Any = error_tracking._before_send(event, {})

    assert time.perf_counter() - started < 1
    assert "hash=f" not in scrubbed["extra"]["url"]


def test_bare_init_data_is_filtered() -> None:
    event: Any = {"extra": {"note": "got query_id=1&user=Ivan&auth_date=1&hash=abc from the client"}}

    assert "Ivan" not in repr(error_tracking._before_send(event, {}))


def test_an_address_after_a_digit_still_loses_its_query() -> None:
    event: Any = {"extra": {"line": "1https://konnekt.cz/x?q=Ivan"}}

    assert "Ivan" not in repr(error_tracking._before_send(event, {}))
