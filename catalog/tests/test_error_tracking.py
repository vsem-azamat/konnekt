"""Errors reach Sentry by name, and nothing secret or personal goes with them."""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from pydantic import SecretStr
from sentry_sdk.transport import Transport

from students_cz.core import error_tracking
from students_cz.core.config import Settings

_TOKEN = "123456789:AAH" + "x" * 32


class Captured(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry(settings: Settings) -> Iterator[Captured]:
    configured = settings.model_copy(
        update={"sentry_dsn": SecretStr("https://key@o0.ingest.sentry.io/0")}
    )
    assert error_tracking.setup_error_tracking(configured)
    transport = Captured()
    sentry_sdk.get_client().transport = transport
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.init(dsn=None)


def test_off_without_a_dsn(settings: Settings) -> None:
    assert error_tracking.setup_error_tracking(settings) is False


def test_an_error_keeps_its_name_and_not_its_fields(sentry: Captured) -> None:
    logging.getLogger("students_cz.x").error(
        "notify_failed", extra={"fields": {"tg_id": 5, "text": "мой номер"}}
    )

    [event] = sentry.events
    assert event["logentry"]["message"] == "notify_failed"
    assert "мой номер" not in repr(event)


@pytest.mark.parametrize(
    ("value", "secret"),
    [
        (f"https://api.telegram.org/bot{_TOKEN}/sendMessage", _TOKEN),
        ("tma query_id=AA&user=%7B%7D&auth_date=1&hash=abc", "query_id=AA"),
        ("call +420 777 123 456 now", "777 123"),
    ],
)
def test_secrets_in_any_value_are_filtered(value: str, secret: str) -> None:
    event = {"extra": {"anything": value}}

    assert secret not in repr(error_tracking._before_send(event, {}))


def test_a_request_keeps_its_route_not_the_ids_or_query_in_it() -> None:
    event = {
        "request": {
            "method": "GET",
            "url": "https://konnekt.cz/api/v1/admin/profiles/555777999?q=Ivan",
            "query_string": "q=Ivan",
            "headers": {"Authorization": "tma user=1"},
        },
        "release": "0064152123456aa7711d",
    }

    scrubbed = error_tracking._before_send(event, {})

    assert scrubbed["request"] == {
        "method": "GET",
        "url": "https://konnekt.cz/api/v1/admin/profiles/:id",
    }
    assert scrubbed["release"] == "0064152123456aa7711d"


async def test_a_deliberate_503_is_not_an_issue(sentry: Captured) -> None:
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()

    @app.get("/down")
    async def down() -> None:
        raise HTTPException(503, "search is off")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/down")).status_code == 503

    assert sentry.events == []
