"""The Mini App says the person opened it; only Telegram's signature makes it true."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from app.core.config import settings
from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

PERSON = 4242


def _init_data(token: str, *, start_param: str | None = None, auth_date: int | None = None, **user: object) -> str:
    fields = {
        "auth_date": str(auth_date or int(datetime.datetime.now(datetime.UTC).timestamp())),
        "user": json.dumps({"id": PERSON, "first_name": "Olena", "language_code": "uk", **user}),
        "signature": "Xf2pQ",
    }
    if start_param is not None:
        fields["start_param"] = start_param
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


@pytest.fixture
def bot_token(monkeypatch) -> str:
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


async def _seen(client, init_data: str):
    return await client.post("/api/public/seen", json={"init_data": init_data})


async def test_an_opened_mini_app_is_recorded_with_its_link(client, bot_token, db_session_maker) -> None:
    response = await _seen(client, _init_data(bot_token, start_param="matfyz", is_premium=True))

    assert response.status_code == 204
    async with db_session_maker() as session:
        member = await session.get(AudienceMember, PERSON)
        touches = [t.touchpoint for t in await session.scalars(select(AudienceTouch))]
        reach = await session.get(AudienceReach, (PERSON, Touchpoint.MAIN_BOT))
    assert member is not None
    assert (member.first_name, member.language_code, member.is_premium, member.source) == (
        "Olena",
        "uk",
        True,
        "matfyz",
    )
    assert touches == [Touchpoint.MINI_APP]
    # Opening the Mini App says nothing about whether the bot may write.
    assert reach is None


async def test_allowing_the_bot_to_write_opens_it(client, bot_token, db_session_maker) -> None:
    await _seen(client, _init_data(bot_token, allows_write_to_pm=True))

    async with db_session_maker() as session:
        reach = await session.get(AudienceReach, (PERSON, Touchpoint.MAIN_BOT))
    assert reach is not None
    assert reach.started_at is not None


async def test_a_forged_payload_records_nothing(client, bot_token, db_session_maker) -> None:
    response = await _seen(client, _init_data("999:not-our-token"))

    assert response.status_code == 403
    async with db_session_maker() as session:
        assert await session.get(AudienceMember, PERSON) is None


async def test_the_visit_is_dated_by_the_launch_and_a_resent_payload_counts_once(
    client, bot_token, db_session_maker
) -> None:
    from app.webapi.routes import seen

    launched = int(datetime.datetime.now(datetime.UTC).timestamp()) - 600
    payload = _init_data(bot_token, auth_date=launched)

    await _seen(client, payload)
    seen.forget()
    await _seen(client, payload)

    async with db_session_maker() as session:
        touch = await session.get(AudienceTouch, (PERSON, Touchpoint.MINI_APP))
    assert touch.count == 1
    assert touch.last_at == datetime.datetime.fromtimestamp(launched, tz=datetime.UTC).replace(tzinfo=None)


async def test_one_person_is_written_at_most_once_in_a_while(client, bot_token, db_session_maker) -> None:
    now = int(datetime.datetime.now(datetime.UTC).timestamp())

    first = await _seen(client, _init_data(bot_token, auth_date=now - 60))
    second = await _seen(client, _init_data(bot_token, auth_date=now))

    assert (first.status_code, second.status_code) == (204, 204)
    async with db_session_maker() as session:
        touch = await session.get(AudienceTouch, (PERSON, Touchpoint.MINI_APP))
    assert touch.count == 1


async def test_a_start_param_none_of_our_links_carry_is_not_kept(client, bot_token, db_session_maker) -> None:
    await _seen(client, _init_data(bot_token, start_param="x" * 65))

    async with db_session_maker() as session:
        member = await session.get(AudienceMember, PERSON)
    assert member.source is None
