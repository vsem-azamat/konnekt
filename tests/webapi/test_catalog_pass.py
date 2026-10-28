"""The endpoint that notes a tap on a catalog chat's join button.

Its credential is Telegram's signature; what it leaves is a pass for the caller
and nobody else, in a chat the bot runs with the captcha on.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from app.core.config import settings
from app.db.models import CatalogPass, Chat
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

CHAT_ID = -1001234
APPLICANT_ID = 4242
LINK = "https://t.me/cvut_fit"


def _epoch() -> int:
    return int(datetime.datetime.now(datetime.UTC).timestamp())


def _init_data(user_id: int, *, token: str, signature: str | None = "Xf2pQ") -> str:
    """The payload a current Telegram client sends, `signature` and all.

    Built without it, this suite stayed green while the captcha refused every
    real applicant for eight days: the field was dropped from the check string,
    so the digest covered less than Telegram had signed.
    """
    fields = {
        "auth_date": str(_epoch()),
        "user": json.dumps({"id": user_id, "first_name": "Applicant", "is_bot": False}),
    }
    if signature is not None:
        fields["signature"] = signature
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


async def _chat(session_maker, *, status: str = Chat.STATUS_APPROVED, mode: str = Chat.JOIN_CAPTCHA) -> None:
    async with session_maker() as session:
        session.add(Chat(id=CHAT_ID, title="ČVUT", resource_status=status, join_mode=mode, public_link=LINK))
        await session.commit()


async def _post(client, init_data: str, link: str = LINK):
    return await client.post("/api/public/catalog-pass", json={"init_data": init_data, "link": link})


async def _passes(session_maker) -> list[CatalogPass]:
    async with session_maker() as session:
        return list((await session.scalars(select(CatalogPass))).all())


async def test_a_tap_leaves_a_pass_for_the_caller(client, db_session_maker, bot_token) -> None:
    await _chat(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 200
    [row] = await _passes(db_session_maker)
    assert (row.user_id, row.chat_id) == (APPLICANT_ID, CHAT_ID)
    hours = (row.expires_at - row.created_at).total_seconds() / 3600
    assert 23.9 < hours < 24.1


async def test_tapping_again_renews_the_one_pass(client, db_session_maker, bot_token) -> None:
    await _chat(db_session_maker)

    await _post(client, _init_data(APPLICANT_ID, token=bot_token))
    second = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert second.status_code == 200
    assert len(await _passes(db_session_maker)) == 1


async def test_a_forged_signature_is_refused(client, db_session_maker, bot_token) -> None:
    await _chat(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token="999:ZZZ-WRONG0987654321"))

    assert response.status_code == 403
    assert await _passes(db_session_maker) == []


async def test_an_unknown_link_is_refused(client, db_session_maker, bot_token) -> None:
    await _chat(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token), link="https://t.me/nope")

    assert response.status_code == 403
    assert response.json() == {"detail": "pass_refused"}
    assert await _passes(db_session_maker) == []


@pytest.mark.parametrize(
    ("status", "mode"),
    [
        (Chat.STATUS_EXTERNAL, Chat.JOIN_CAPTCHA),
        (Chat.STATUS_OBSERVED, Chat.JOIN_CAPTCHA),
        (Chat.STATUS_APPROVED, Chat.JOIN_ADMINS),
        (Chat.STATUS_APPROVED, Chat.JOIN_OPEN),
    ],
)
async def test_only_a_chat_with_the_captcha_on_gives_a_pass(client, db_session_maker, bot_token, status, mode) -> None:
    await _chat(db_session_maker, status=status, mode=mode)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 403
    assert await _passes(db_session_maker) == []


async def test_it_can_be_turned_off(client, db_session_maker, bot_token, monkeypatch) -> None:
    monkeypatch.setattr(settings.captcha, "catalog_pass_hours", 0)
    await _chat(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 403
    assert await _passes(db_session_maker) == []
