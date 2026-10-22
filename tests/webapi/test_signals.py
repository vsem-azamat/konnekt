"""The console's signals: what waits for an admin's decision, and the queues."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.enums import PendingActionStatus
from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot, JoinCaptcha, JoinWave, PendingAction, SpamPing, User
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_session, None)


def _captcha(chat_id: int, user_id: int, status: str, wave_id: int | None, now: datetime.datetime) -> JoinCaptcha:
    return JoinCaptcha(
        chat_id=chat_id,
        user_id=user_id,
        user_chat_id=user_id,
        status=status,
        answer="🍎",
        options=["🍎"],
        attempts_left=3,
        created_at=now,
        expires_at=now + datetime.timedelta(minutes=15),
        wave_id=wave_id,
    )


async def _signals(client: AsyncClient) -> dict:
    async with client:
        response = await client.get("/api/signals")
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_wave_nobody_decided_waits_with_the_requests_it_holds(client, db_session_maker) -> None:
    now = utc_now()
    async with db_session_maker() as session:
        session.add(Chat(id=-100, title="Matfyz"))
        session.add(ChatMemberSnapshot(chat_id=-100, member_count=461, captured_at=now))
        waiting = JoinWave(chat_id=-100, started_at=now - datetime.timedelta(minutes=20))
        waiting.last_surge_at = now - datetime.timedelta(minutes=6)
        decided = JoinWave(chat_id=-100, started_at=now - datetime.timedelta(days=1))
        decided.decision = JoinWave.DECISION_DECLINE
        session.add_all([waiting, decided])
        await session.flush()
        session.add_all(
            [_captcha(-100, user_id, JoinCaptcha.STATUS_HELD, waiting.id, now) for user_id in range(1, 4)]
            + [
                _captcha(-100, 10, JoinCaptcha.STATUS_DECLINED, waiting.id, now),
                _captcha(-100, 11, JoinCaptcha.STATUS_HELD, decided.id, now),
            ]
        )
        await session.commit()
        waiting_id = waiting.id

    body = await _signals(client)

    assert [wave["id"] for wave in body["waves"]] == [waiting_id]
    wave = body["waves"][0]
    assert wave["chat_id"] == -100
    assert wave["chat_title"] == "Matfyz"
    assert wave["member_count"] == 461
    assert wave["held"] == 3
    # Six minutes since the last burst is within the quiet spell: still paused.
    assert wave["paused"] is True


async def test_a_wave_whose_held_requests_are_all_settled_waits_for_nothing(client, db_session_maker) -> None:
    now = utc_now()
    async with db_session_maker() as session:
        session.add(Chat(id=-100, title="Matfyz"))
        wave = JoinWave(chat_id=-100, started_at=now - datetime.timedelta(hours=2))
        wave.last_surge_at = now - datetime.timedelta(hours=2)
        session.add(wave)
        await session.flush()
        session.add(_captcha(-100, 1, JoinCaptcha.STATUS_EXPIRED, wave.id, now))
        await session.commit()

    assert (await _signals(client))["waves"] == []


async def test_a_ban_proposed_through_mcp_waits_until_pressed_or_expired(client, db_session_maker) -> None:
    now = utc_now()
    async with db_session_maker() as session:
        session.add(Chat(id=-100, title="Kolej"))
        session.add(User(id=7000199, username="promo", first_name="Promo"))
        open_ban = PendingAction(
            origin="mcp",
            initiator_id=1,
            action="ban",
            target_user_id=7000199,
            chat_id=None,
            reason="3 ads in an hour",
            expires_at=now + datetime.timedelta(minutes=40),
        )
        expired = PendingAction(
            origin="mcp", initiator_id=1, action="ban", target_user_id=2, expires_at=now - datetime.timedelta(minutes=1)
        )
        confirmed = PendingAction(
            origin="mcp", initiator_id=1, action="blacklist", target_user_id=3, chat_id=-100, expires_at=now
        )
        confirmed.status = PendingActionStatus.CONFIRMED
        session.add_all([open_ban, expired, confirmed])
        await session.commit()
        open_id = open_ban.id

    body = await _signals(client)

    assert [action["id"] for action in body["pending_actions"]] == [open_id]
    action = body["pending_actions"][0]
    assert action["action"] == "ban"
    assert action["chat_id"] is None
    assert action["target_user_id"] == 7000199
    assert action["target_username"] == "promo"
    assert action["target_name"] == "Promo"
    assert action["reason"] == "3 ads in an hour"


async def test_the_queues_count_unreviewed_ads_and_chats_under_review(client, db_session_maker) -> None:
    now = utc_now()
    async with db_session_maker() as session:
        session.add_all(
            [
                Chat(id=-1, title="New", resource_status=Chat.STATUS_DISCOVERED),
                Chat(id=-2, title="Also new", resource_status=Chat.STATUS_DISCOVERED),
                Chat(id=-3, title="Ours", resource_status=Chat.STATUS_APPROVED),
            ]
        )
        session.add(
            SpamPing(chat_id=-3, user_id=5, message_id=1, kind="link", matches=["bit.ly"], snippet="x", detected_at=now)
        )
        await session.commit()

    body = await _signals(client)

    assert body["queues"] == {"ads_unreviewed": 1, "chats_in_review": 2}
    assert body["waves"] == []
    assert body["pending_actions"] == []
