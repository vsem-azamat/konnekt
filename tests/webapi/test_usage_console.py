"""The console's «Использование» and «Источники», counted from what the app and the daily import wrote."""

from __future__ import annotations

import datetime
import json

import httpx
import pytest
from app.core.config import settings
from app.db.models import ProductEvent, SearchDay, SiteDay
from app.usage import report, sources
from app.webapi.main import app
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

# A Tuesday, 12:00 in Prague (UTC+1 in November).
NOW = datetime.datetime(2026, 11, 10, 11, 0)


def _ev(user: int, session: str, name: str, minutes: float, screen: str | None = None, **props) -> ProductEvent:
    return ProductEvent(
        user_id=user,
        session=session,
        seq=int(minutes * 10),
        name=name,
        screen=screen,
        props=props,
        at=NOW - datetime.timedelta(minutes=minutes),
        platform="ios",
        version="t",
    )


@pytest.fixture
async def written(db_session_maker) -> None:
    async with db_session_maker() as db:
        db.add_all(
            [
                # One person found somebody and wrote to them, over four minutes, still in the app.
                _ev(1, "a", "session_start", 4, source="site_hero"),
                _ev(1, "a", "screen_view", 4, "/home"),
                _ev(1, "a", "search_submit", 3.5, "/results", results=0),
                _ev(1, "a", "search_submit", 3, "/results", results=2),
                _ev(1, "a", "helper_open", 2.5, "/results", **{"from": "results"}),
                _ev(1, "a", "contact_tap", 2, "/helper/:id", **{"from": "helper"}),
                _ev(1, "a", "heartbeat", 0.5, "/helper/:id"),
                # Another opened a helper before searching: their search is a step, the helper is not.
                _ev(2, "b", "session_start", 60 * 25),
                _ev(2, "b", "helper_open", 60 * 25 - 1, "/home", **{"from": "home"}),
                _ev(2, "b", "search_submit", 60 * 25 - 2, "/results", results=1),
                _ev(2, "b", "tab_tap", 60 * 25 - 3, "/home", tab="chats"),
                _ev(2, "b", "screen_view", 60 * 25 - 3, "/chats"),
                _ev(2, "c", "session_start", 60 * 24, resumed=True),
                # Long ago: outside every period.
                _ev(3, "d", "session_start", 60 * 24 * 40),
            ]
        )
        await db.commit()


async def test_usage_counts_sessions_people_and_who_is_in_the_app(db_session_maker, written) -> None:
    async with db_session_maker() as db:
        got = await report.usage(db, days=7, now=NOW)

    assert (got["online"], got["people"], got["sessions"]) == (1, 2, 3)
    # a: 4 minutes to 30 seconds ago plus one beat; b: 3 minutes plus a beat; c: one event, one beat.
    assert {(length["from_seconds"], length["sessions"]) for length in got["lengths"] if length["sessions"]} == {
        (30, 1),
        (180, 2),
    }
    assert got["since"] == NOW - datetime.timedelta(days=40)
    assert got["by_day"][-1] == {"day": datetime.date(2026, 11, 10), "sessions": 1, "people": 1}
    assert {"weekday": 1, "hour": 11, "people": 1} in got["heat"]  # 10:56 to 11:00 UTC is 11:56 to 12:00 in Prague
    assert got["screens"] == [{"screen": "/chats", "people": 1}, {"screen": "/home", "people": 1}]
    assert {"name": "tab_tap", "detail": "chats", "count": 1} in got["taps"]
    assert {"source": "site_hero", "launches": 1} in got["entries"]
    assert {"source": None, "launches": 1} in got["entries"]  # session b; c was resumed
    find = next(f for f in got["funnels"] if f["key"] == "find")
    # Person 2 searched and found after opening a helper: «found» counts, the helper before it does not.
    assert [s["people"] for s in find["steps"]] == [2, 2, 2, 1, 1]


def test_one_search_that_finds_somebody_is_both_steps() -> None:
    at = NOW
    events: list[tuple[int, datetime.datetime, int, str, str | None, dict]] = [
        (1, at, 0, "session_start", None, {}),
        (1, at, 1, "search_submit", "/results", {"results": 3}),
        (1, at, 2, "helper_open", "/helper/:id", {"from": "results"}),
        (1, at, 3, "contact_tap", "/helper/:id", {"from": "helper"}),
    ]
    assert report._funnel(report.FUNNELS["find"], events) == [1, 1, 1, 1, 1]


def test_hours_are_the_readers_and_skip_the_hour_that_does_not_exist() -> None:
    from zoneinfo import ZoneInfo

    prague = ZoneInfo("Europe/Prague")
    # 29 March 2026, the clocks go from 02:00 to 03:00 in Prague: 00:50 to 01:10 UTC is 01:50 to 03:10.
    slots = report._hours(datetime.datetime(2026, 3, 29, 0, 50), datetime.datetime(2026, 3, 29, 1, 10), prague)
    assert slots == {(6, 1), (6, 3)}
    # The same hour read in New York.
    assert report._hours(NOW, NOW, ZoneInfo("America/New_York")) == {(1, 6)}
    # Half an hour off UTC: 10:40 to 10:50 UTC is 16:10 to 16:20 in Kolkata, one hour.
    kolkata = report._hours(
        datetime.datetime(2026, 11, 10, 10, 40), datetime.datetime(2026, 11, 10, 10, 50), ZoneInfo("Asia/Kolkata")
    )
    assert kolkata == {(1, 16)}


async def test_the_route_reads_in_the_readers_zone(db_session_maker, written) -> None:
    from app.webapi.deps import get_session

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.get("/api/usage?days=7&tz=America/New_York")).status_code == 200
            # A zone the server does not know reads in the default one rather than failing the screen.
            assert (await client.get("/api/usage?days=7&tz=Mars/Olympus")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_the_console_routes_answer_and_refuse_odd_periods(db_session_maker, written) -> None:
    from app.webapi.deps import get_session

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.get("/api/usage?days=30")).status_code == 200
            assert (await client.get("/api/usage?days=14")).status_code == 422
            body = (await client.get("/api/usage/sources?days=30")).json()
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert body["site"]["on"] is False
    assert body["search"]["on"] is False


def _service_account() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return json.dumps({"client_email": "konnekt@example.iam.gserviceaccount.com", "private_key": pem.decode()})


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.cloudflare.com":
        assert request.headers["authorization"] == "Bearer cf-token"
        day = {"date": "2026-11-09"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "viewer": {
                        "accounts": [
                            {
                                "total": [{"count": 30, "sum": {"visits": 12}, "dimensions": day}],
                                "referrer": [
                                    {
                                        "count": 20,
                                        "sum": {"visits": 8},
                                        "dimensions": {**day, "refererHost": "www.google.com"},
                                    },
                                    {"count": 10, "sum": {"visits": 4}, "dimensions": {**day, "refererHost": ""}},
                                ],
                                "page": [
                                    {"count": 30, "sum": {"visits": 12}, "dimensions": {**day, "requestPath": "/"}}
                                ],
                            }
                        ]
                    }
                }
            },
        )
    if request.url.host == "oauth2.googleapis.com":
        return httpx.Response(200, json={"access_token": "g-token"})
    assert request.headers["authorization"] == "Bearer g-token"
    assert "sc-domain%3Akonnekt.cz" in str(request.url)
    dims = json.loads(request.content)["dimensions"]
    keys = ["2026-11-08"] if dims == ["date"] else ["2026-11-08", "nostrifikace"]
    return httpx.Response(200, json={"rows": [{"keys": keys, "clicks": 3, "impressions": 40, "position": 5.5}]})


async def test_the_import_writes_both_services_days_and_rewrites_them(db_session_maker, monkeypatch) -> None:
    from pydantic import SecretStr

    config = settings.analytics
    monkeypatch.setattr(config, "cloudflare_token", SecretStr("cf-token"))
    monkeypatch.setattr(config, "cloudflare_account_id", "acc")
    monkeypatch.setattr(config, "cloudflare_site_tag", "site")
    monkeypatch.setattr(config, "search_console_credentials", SecretStr(_service_account()))
    today = datetime.date(2026, 11, 10)

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as http, db_session_maker() as db:
        await sources.import_once(db, http, today=today)
        await sources.import_once(db, http, today=today)
        site = list(await db.scalars(select(SiteDay).order_by(SiteDay.dimension, SiteDay.key)))
        search = list(await db.scalars(select(SearchDay).order_by(SearchDay.query)))
        got = await sources.report(db, days=7, today=today)

    assert [(s.dimension, s.key, s.visits) for s in site] == [
        ("page", "/", 12),
        ("referrer", "*", 4),
        ("referrer", "www.google.com", 8),
        ("total", "*", 12),
    ]
    assert [(s.query, s.clicks) for s in search] == [("*", 3), ("nostrifikace", 3)]
    assert (got["site"]["visits"], got["site"]["through"]) == (12, datetime.date(2026, 11, 9))
    assert got["search"]["queries"] == [{"query": "nostrifikace", "clicks": 3, "impressions": 40, "position": 5.5}]


async def test_a_launch_from_a_helpers_page_on_the_site_counts_as_from_the_site(db_session_maker) -> None:
    async with db_session_maker() as db:
        db.add(_ev(1, "a", "session_start", 60 * 24, source="site_helper"))
        await db.commit()
        got = await sources.report(db, days=7, today=NOW.date())
    assert got["to_app"] == {"launches": 1, "by_source": [{"source": "site_helper", "launches": 1}]}


async def test_a_failing_service_leaves_the_other_and_says_why(db_session_maker, monkeypatch) -> None:
    from pydantic import SecretStr

    config = settings.analytics
    monkeypatch.setattr(config, "cloudflare_token", SecretStr("cf-token"))
    monkeypatch.setattr(config, "cloudflare_account_id", "acc")
    monkeypatch.setattr(config, "cloudflare_site_tag", "site")
    monkeypatch.setattr(config, "search_console_credentials", SecretStr(""))

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None, "errors": [{"message": "x", "path": ["viewer"]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as http, db_session_maker() as db:
        await sources.import_once(db, http, today=datetime.date(2026, 11, 10))
        assert list(await db.scalars(select(SiteDay))) == []
