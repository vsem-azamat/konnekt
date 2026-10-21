"""The Mini App reports its own failures: a log line and a counter, nothing about the person."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
import structlog
from app.core.config import settings
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

pytestmark = pytest.mark.asyncio

PERSON = 4242


def _init_data(token: str, *, person: int = PERSON, age: int = 0) -> str:
    fields = {
        "auth_date": str(int(datetime.datetime.now(datetime.UTC).timestamp()) - age),
        "user": json.dumps({"id": person, "first_name": "Olena", "username": "olena_k"}),
        "signature": "Xf2pQ",
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


@pytest.fixture
def bot_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "123456:ABC-DEF1234567890"  # noqa: S105 — test fixture
    monkeypatch.setattr(settings.telegram, "token", token)
    return token


@pytest.fixture(autouse=True)
def uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """structlog caches a logger on first use, and then `capture_logs` cannot reach it."""
    from app.webapi.routes import client_errors

    monkeypatch.setattr(client_errors, "logger", structlog.get_logger("webapi.client_errors"))


def _event(**overrides: object) -> dict[str, object]:
    return {"kind": "error", "message": "TypeError: x is undefined", "route": "/chats/:group", **overrides}


def _report(init_data: str, *events: dict[str, object], **overrides: object) -> dict[str, object]:
    return {
        "init_data": init_data,
        "version": "f51507a",
        "platform": "android",
        "tg_version": "9.1",
        "events": list(events) or [_event()],
        **overrides,
    }


async def _post(body: object) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post("/api/public/client-errors", json=body)
    return response.status_code


def _count(kind: str, platform: str = "android") -> float:
    return REGISTRY.get_sample_value("mini_app_client_errors_total", {"kind": kind, "platform": platform}) or 0.0


def _dropped(reason: str) -> float:
    return REGISTRY.get_sample_value("mini_app_client_errors_dropped_total", {"reason": reason}) or 0.0


async def test_a_reported_error_is_one_warning_line_and_one_count(bot_token: str) -> None:
    before = _count("api")
    event = _event(kind="api", endpoint="/api/v1/me", status=502, message="")
    with structlog.testing.capture_logs() as logs:
        status = await _post(_report(_init_data(bot_token), event))

    assert status == 204
    assert _count("api") == before + 1
    [line] = [entry for entry in logs if entry["event"] == "client_error"]
    assert line["log_level"] == "warning"
    assert (line["kind"], line["route"], line["endpoint"], line["status"]) == (
        "api",
        "/chats/:group",
        "/api/v1/me",
        502,
    )
    assert (line["version"], line["platform"], line["tg_version"]) == ("f51507a", "android", "9.1")


async def test_the_line_says_nothing_about_who_sent_it(bot_token: str) -> None:
    init_data = _init_data(bot_token)
    with structlog.testing.capture_logs() as logs:
        await _post(_report(init_data))

    written = json.dumps(logs, default=str)
    for secret in (str(PERSON), "Olena", "olena_k", init_data, "hash"):
        assert secret not in written


async def test_an_address_in_a_message_loses_its_query_and_fragment(bot_token: str) -> None:
    message = "failed at https://app.example/chats#tgWebAppData=user%3D42 and https://x.example/a?token=abc"
    with structlog.testing.capture_logs() as logs:
        await _post(
            _report(_init_data(bot_token), _event(message=message, stack="at https://app.example/#tgWebAppData=1"))
        )

    [line] = [entry for entry in logs if entry["event"] == "client_error"]
    assert line["message"] == "failed at https://app.example/chats and https://x.example/a"
    assert "tgWebAppData" not in line["stack"]


async def test_long_numbers_are_not_kept(bot_token: str) -> None:
    with structlog.testing.capture_logs() as logs:
        await _post(_report(_init_data(bot_token), _event(message="no member 987654321 in -1001234567890")))

    [line] = [entry for entry in logs if entry["event"] == "client_error"]
    assert "987654321" not in line["message"]
    assert "1234567890" not in line["message"]


async def test_a_platform_we_do_not_know_is_counted_as_other(bot_token: str) -> None:
    before = _count("error", "other")
    await _post(_report(_init_data(bot_token), platform="something-new"))
    assert _count("error", "other") == before + 1


async def test_an_unsigned_report_is_refused_and_not_counted(bot_token: str) -> None:
    before = _count("error")
    assert await _post(_report("user=%7B%22id%22%3A1%7D&hash=00")) == 403
    assert _count("error") == before


async def test_a_launch_older_than_an_hour_may_still_report(bot_token: str) -> None:
    # The Mini App stays open for as long as somebody leaves it open, and the
    # failure worth knowing about is often the one after hours in the background.
    assert await _post(_report(_init_data(bot_token, age=6 * 3600))) == 204


@pytest.mark.parametrize(
    "event",
    [
        _event(kind="nonsense"),
        _event(route="https://elsewhere.example/"),
        _event(endpoint="/api/v1/me?token=1"),
        _event(status=1000),
        _event(message="x" * 2000),
    ],
)
async def test_a_malformed_event_is_skipped_and_the_rest_are_kept(bot_token: str, event: dict[str, object]) -> None:
    dropped = _dropped("invalid")
    with structlog.testing.capture_logs() as logs:
        status = await _post(_report(_init_data(bot_token), event, _event(message="the good one")))

    assert status == 204
    assert [entry["message"] for entry in logs if entry["event"] == "client_error"] == ["the good one"]
    assert _dropped("invalid") == dropped + 1


async def test_a_malformed_report_is_refused_without_echoing_it(bot_token: str) -> None:
    init_data = _init_data(bot_token)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post("/api/public/client-errors", json=_report(init_data, version="not a word"))
    assert response.status_code == 422
    assert init_data not in response.text


async def test_a_launch_older_than_a_day_may_not(bot_token: str) -> None:
    assert await _post(_report(_init_data(bot_token, age=25 * 3600))) == 403


async def test_a_new_window_lets_everybody_report_again(bot_token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.webapi.routes import client_errors

    now = [1000.0]
    monkeypatch.setattr(client_errors.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(client_errors, "OVERALL", client_errors.PER_PERSON + 1)
    for _ in range(client_errors.PER_PERSON // 10 + 1):
        await _post(_report(_init_data(bot_token), *[_event()] * 10))
    await _post(_report(_init_data(bot_token, person=7), *[_event()] * 10))

    now[0] += client_errors.WINDOW_SECONDS
    with structlog.testing.capture_logs() as logs:
        await _post(_report(_init_data(bot_token)))
        await _post(_report(_init_data(bot_token, person=7)))
    assert [entry["event"] for entry in logs].count("client_error") == 2


async def test_a_bare_init_data_and_odd_schemes_are_scrubbed(bot_token: str) -> None:
    message = "x #tgWebAppData=user%3D42 TG://resolve?domain=me WSS://h.example/s?k=1"
    with structlog.testing.capture_logs() as logs:
        await _post(_report(_init_data(bot_token), _event(message=message, route="/helper/1234567890")))

    [line] = [entry for entry in logs if entry["event"] == "client_error"]
    assert "user%3D42" not in line["message"]
    assert "domain=me" not in line["message"]
    assert "k=1" not in line["message"]
    assert "1234567890" not in line["route"]


async def test_a_report_carries_a_bounded_number_of_events(bot_token: str) -> None:
    assert await _post(_report(_init_data(bot_token), *[_event()] * 21)) == 422


async def test_a_body_past_the_cap_is_refused_before_it_is_parsed(bot_token: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            "/api/public/client-errors",
            content=b"{" + b" " * 70_000 + b"}",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


async def test_one_person_cannot_flood_the_log(bot_token: str) -> None:
    from app.webapi.routes import client_errors

    init_data = _init_data(bot_token)
    dropped = _dropped("rate_limited")
    with structlog.testing.capture_logs() as logs:
        for _ in range(client_errors.PER_PERSON // 10 + 2):
            assert await _post(_report(init_data, *[_event()] * 10)) == 204

    lines = [entry for entry in logs if entry["event"] == "client_error"]
    assert len(lines) == client_errors.PER_PERSON
    assert _dropped("rate_limited") == dropped + 20


async def test_somebody_else_still_gets_through(bot_token: str) -> None:
    from app.webapi.routes import client_errors

    for _ in range(client_errors.PER_PERSON // 10 + 1):
        await _post(_report(_init_data(bot_token), *[_event()] * 10))
    with structlog.testing.capture_logs() as logs:
        await _post(_report(_init_data(bot_token, person=7)))
    assert [entry["event"] for entry in logs].count("client_error") == 1


async def test_everybody_together_is_capped_too(bot_token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.webapi.routes import client_errors

    monkeypatch.setattr(client_errors, "OVERALL", 3)
    dropped = _dropped("overall_limit")
    with structlog.testing.capture_logs() as logs:
        for person in range(1, 6):
            await _post(_report(_init_data(bot_token, person=person)))
    assert [entry["event"] for entry in logs].count("client_error") == 3
    assert _dropped("overall_limit") == dropped + 2
