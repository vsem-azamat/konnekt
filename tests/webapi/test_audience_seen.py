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


def _init_data(token: str, *, start_param: str | None = None, **user: object) -> str:
    fields = {
        "auth_date": str(int(datetime.datetime.now(datetime.UTC).timestamp())),
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
