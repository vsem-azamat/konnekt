"""The Mini App says what people did in it: our own words only, about the person Telegram signed."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from app.core.config import settings
from app.db.models import ProductEvent
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

PERSON = 4242
SESSION = "0f8e2c1a-7b3d-4e5f-9a10-2b3c4d5e6f70"


def _init_data(token: str, *, person: int = PERSON, start_param: str | None = None) -> str:
    fields = {
        "auth_date": str(int(datetime.datetime.now(datetime.UTC).timestamp())),
        "user": json.dumps({"id": person, "first_name": "Olena", "username": "olena_k"}),
        "signature": "Xf2pQ",
    }
    if start_param is not None:
        fields["start_param"] = start_param
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


@pytest.fixture
def bot_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "123456:ABC-DEF1234567890"  # noqa: S105 — test fixture
    monkeypatch.setattr(settings.telegram, "token", token)
    return token


@pytest.fixture
def client(db_session_maker):
    from app.webapi.deps import get_session

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_session, None)


def _event(name: str = "screen_view", seq: int = 0, **overrides: object) -> dict[str, object]:
    return {"name": name, "at": int(time.time() * 1000), "seq": seq, "session": SESSION, "screen": "/home", **overrides}


def _batch(init_data: str, *events: dict[str, object]) -> dict[str, object]:
    return {"init_data": init_data, "version": "f51507a", "platform": "android", "events": list(events) or [_event()]}


async def _rows(db_session_maker) -> list[ProductEvent]:
    async with db_session_maker() as session:
        return list(await session.scalars(select(ProductEvent).order_by(ProductEvent.seq)))


def _dropped(reason: str) -> float:
    return REGISTRY.get_sample_value("mini_app_events_dropped_total", {"reason": reason}) or 0.0


async def test_events_are_written_for_the_person_telegram_signed(client, bot_token, db_session_maker) -> None:
    body = _batch(
        _init_data(bot_token),
        _event("session_start", 0, props={"resumed": False}),
        _event("tab_tap", 1, props={"tab": "chats"}),
        _event("search_submit", 2, screen="/results", props={"results": 3, "filters": 1}),
    )
    body["user_id"] = 1  # a body naming somebody else changes nothing

    response = await client.post("/api/public/events", json=body)

    assert response.status_code == 204
    rows = await _rows(db_session_maker)
    assert [(r.user_id, r.name, r.props) for r in rows] == [
        (PERSON, "session_start", {"resumed": False}),
        (PERSON, "tab_tap", {"tab": "chats"}),
        (PERSON, "search_submit", {"results": 3, "filters": 1}),
    ]
    assert {(r.platform, r.version, r.session) for r in rows} == {("android", "f51507a", SESSION)}


async def test_a_launch_keeps_the_link_telegram_signed_and_a_resumed_session_does_not(
    client, bot_token, db_session_maker
) -> None:
    init_data = _init_data(bot_token, start_param="site_hero")
    await client.post(
        "/api/public/events",
        json=_batch(init_data, _event("session_start", 0), _event("session_start", 1, props={"resumed": True})),
    )

    rows = await _rows(db_session_maker)
    assert [r.props for r in rows] == [{"source": "site_hero"}, {"resumed": True}]


@pytest.mark.parametrize(
    ("start_param", "kept"),
    [("helper-12345", "site_helper"), ("uni-cvut", "uni-cvut"), ("site_hero", "site_hero"), ("x1234567", None)],
)
async def test_a_launch_link_is_kept_as_a_word_never_as_somebodys_id(
    client, bot_token, db_session_maker, start_param, kept
) -> None:
    await client.post(
        "/api/public/events", json=_batch(_init_data(bot_token, start_param=start_param), _event("session_start"))
    )

    (row,) = await _rows(db_session_maker)
    assert row.props.get("source") == kept


@pytest.mark.parametrize(
    "event",
    [
        _event("typed_something"),
        _event("tab_tap", props={"tab": "Что-то, что человек написал"}),
        _event("tab_tap", props={"query": "chats"}),
        _event("search_submit", props={"results": -1}),
        _event(screen="https://konnekt.cz/helper/12345?x=1"),
        _event(screen="/helper/12345"),
        _event(at=10**15),
        _event(props={"source": "site_hero"}),
    ],
)
async def test_anything_but_our_own_words_is_dropped_and_counted(client, bot_token, db_session_maker, event) -> None:
    before = _dropped("invalid")

    response = await client.post("/api/public/events", json=_batch(_init_data(bot_token), event, _event(seq=1)))

    assert response.status_code == 204
    assert [r.seq for r in await _rows(db_session_maker)] == [1]
    assert _dropped("invalid") == before + 1


async def test_an_unsigned_batch_writes_nothing(client, bot_token, db_session_maker) -> None:
    response = await client.post("/api/public/events", json=_batch(_init_data("1:other-bot")))

    assert response.status_code == 403
    assert await _rows(db_session_maker) == []


async def test_a_clock_far_off_is_replaced_by_the_servers(client, bot_token, db_session_maker) -> None:
    await client.post("/api/public/events", json=_batch(_init_data(bot_token), _event(at=0)))

    (row,) = await _rows(db_session_maker)
    assert abs(row.at - datetime.datetime.now(datetime.UTC).replace(tzinfo=None)) < datetime.timedelta(minutes=1)


async def test_one_person_cannot_fill_the_table(client, bot_token, db_session_maker, monkeypatch) -> None:
    from app.webapi.routes import events

    monkeypatch.setattr(events, "PER_PERSON", 3)
    before = _dropped("rate_limited")
    init_data = _init_data(bot_token)

    await client.post("/api/public/events", json=_batch(init_data, *(_event(seq=i) for i in range(2))))
    await client.post("/api/public/events", json=_batch(init_data, *(_event(seq=i) for i in range(2, 4))))

    assert [r.seq for r in await _rows(db_session_maker)] == [0, 1, 2]
    assert _dropped("rate_limited") == before + 1
