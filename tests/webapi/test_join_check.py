"""The public endpoint a Mini App calls to pass the join check.

Public in the sense that it carries no admin session — its authentication is
Telegram's own signature over initData. What it must never allow is one person
passing the check on another's behalf, which is how a farm of accounts would
let each other in.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from app.core.config import settings
from app.db.models import Chat, JoinCheck
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

CHAT_ID = -1001234
APPLICANT_ID = 4242
OTHER_ID = 999
QUERY_ID = "q-abc"


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
def join_bot():
    return AsyncMock()


@pytest.fixture
def client(db_session_maker, join_bot):
    from app.webapi.deps import get_publish_bot, get_session

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_publish_bot] = lambda: join_bot
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


async def _seed(
    session_maker, *, minutes: int = 10, user_id: int = APPLICANT_ID, chat_status: str = Chat.STATUS_APPROVED
) -> None:
    from app.core.time import utc_now

    async with session_maker() as session:
        # A check is only ever issued in a chat the bot moderates.
        session.add(Chat(id=CHAT_ID, title="Moderated", resource_status=chat_status))
        session.add(
            JoinCheck(
                query_id=QUERY_ID,
                chat_id=CHAT_ID,
                user_id=user_id,
                expires_at=utc_now() + datetime.timedelta(minutes=minutes),
            )
        )
        await session.commit()


async def _post(client, init_data: str, query_id: str = QUERY_ID):
    return await client.post("/api/public/join-check", json={"init_data": init_data, "query_id": query_id})


async def test_the_applicant_is_approved(client, db_session_maker, bot_token, join_bot) -> None:
    await _seed(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    join_bot.answer_chat_join_request_query.assert_awaited_once_with(
        chat_join_request_query_id=QUERY_ID, result="approve"
    )


async def test_somebody_else_cannot_pass_it_for_them(client, db_session_maker, bot_token, join_bot) -> None:
    """The whole point: a query id in the wrong hands stays useless."""
    await _seed(db_session_maker)

    response = await _post(client, _init_data(OTHER_ID, token=bot_token))

    assert response.status_code == 403
    join_bot.answer_chat_join_request_query.assert_not_awaited()


async def test_a_forged_signature_is_refused(client, db_session_maker, bot_token, join_bot) -> None:
    await _seed(db_session_maker)

    response = await _post(client, _init_data(APPLICANT_ID, token="999:ZZZ-WRONG0987654321"))

    assert response.status_code == 403
    join_bot.answer_chat_join_request_query.assert_not_awaited()


async def test_an_expired_check_is_refused(client, db_session_maker, bot_token, join_bot) -> None:
    await _seed(db_session_maker, minutes=-1)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 403
    join_bot.answer_chat_join_request_query.assert_not_awaited()


async def test_an_unknown_query_is_refused(client, db_session_maker, bot_token, join_bot) -> None:
    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token), query_id="nope")

    assert response.status_code == 403
    join_bot.answer_chat_join_request_query.assert_not_awaited()


async def test_passing_twice_answers_once(client, db_session_maker, bot_token, join_bot) -> None:
    """Telegram accepts one answer per query; a double tap must not send two."""
    await _seed(db_session_maker)

    first = await _post(client, _init_data(APPLICANT_ID, token=bot_token))
    second = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert first.status_code == 200
    assert second.status_code == 403
    assert join_bot.answer_chat_join_request_query.await_count == 1


async def test_passing_is_recorded(client, db_session_maker, bot_token, join_bot) -> None:
    await _seed(db_session_maker)

    await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    async with db_session_maker() as session:
        row = await session.scalar(select(JoinCheck).where(JoinCheck.query_id == QUERY_ID))
    assert row is not None
    assert row.passed_at is not None


async def test_a_check_telegram_could_not_be_told_about_can_be_retried(
    client, db_session_maker, bot_token, join_bot
) -> None:
    """Recorded before the call, a failed call used to burn the applicant's only check."""
    from aiogram.exceptions import TelegramNetworkError

    await _seed(db_session_maker)
    join_bot.answer_chat_join_request_query.side_effect = [
        TelegramNetworkError(method=AsyncMock(), message="timeout"),
        None,
    ]

    first = await _post(client, _init_data(APPLICANT_ID, token=bot_token))
    second = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert first.status_code == 503
    assert second.status_code == 200
    assert join_bot.answer_chat_join_request_query.await_count == 2


async def test_a_query_telegram_refuses_stays_spent(client, db_session_maker, bot_token, join_bot) -> None:
    """Refused outright means answered already or gone: answering again cannot help."""
    from aiogram.exceptions import TelegramBadRequest

    await _seed(db_session_maker)
    join_bot.answer_chat_join_request_query.side_effect = TelegramBadRequest(
        method=AsyncMock(), message="QUERY_ID_INVALID"
    )

    first = await _post(client, _init_data(APPLICANT_ID, token=bot_token))
    second = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert first.status_code == 409
    assert second.status_code == 403
    assert join_bot.answer_chat_join_request_query.await_count == 1


@pytest.mark.parametrize("chat_status", [Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL, Chat.STATUS_DISABLED])
async def test_a_chat_no_longer_moderated_lets_nobody_in(
    client, db_session_maker, bot_token, join_bot, chat_status
) -> None:
    """Issued while the bot ran the door; passed after it stopped: the door is its owner's again."""
    await _seed(db_session_maker, chat_status=chat_status)

    response = await _post(client, _init_data(APPLICANT_ID, token=bot_token))

    assert response.status_code == 403
    join_bot.answer_chat_join_request_query.assert_not_awaited()
