"""Deciding from the console what the bot asks about in the report chat and in private.

The console's press is the bot's press: the same service decides, and the
bot's message loses its buttons and says what happened, so the two never
disagree about whether something is still open.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import settings
from app.core.enums import ModerationEventAction, PendingActionStatus
from app.core.time import utc_now
from app.db.models import Chat, JoinCaptcha, JoinWave, ModerationEvent, PendingAction, User
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

ADMIN = 1


@pytest.fixture
def bot() -> MagicMock:
    fake = MagicMock()
    fake.edit_message_text = AsyncMock()
    fake.decline_chat_join_request = AsyncMock()
    fake.ban_chat_member = AsyncMock()
    return fake


@pytest.fixture
def client(db_session_maker: async_sessionmaker[AsyncSession], bot, monkeypatch):
    from app.webapi.deps import get_publish_bot, get_session
    from app.webapi.routes import signals

    async def _session():
        async with db_session_maker() as session:
            yield session

    async def _bot():
        return bot

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_publish_bot] = _bot
    # The wave's work runs after the answer, in a session of its own.
    monkeypatch.setattr(signals, "get_session_maker", lambda: db_session_maker)
    monkeypatch.setattr(settings.admin, "super_admins", [ADMIN])
    monkeypatch.setattr(settings.admin, "report_chat_id", -500)
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


async def _wave(db_session_maker, *, held: int, decision: str | None = None) -> int:
    now = utc_now()
    async with db_session_maker() as session:
        session.add(Chat(id=-100, title="Matfyz", resource_status=Chat.STATUS_APPROVED, is_captcha_enabled=True))
        wave = JoinWave(chat_id=-100, started_at=now - datetime.timedelta(minutes=5))
        wave.alert_message_id = 77
        wave.decision = decision
        session.add(wave)
        await session.flush()
        session.add_all(
            JoinCaptcha(
                chat_id=-100,
                user_id=user_id,
                user_chat_id=user_id,
                status=JoinCaptcha.STATUS_HELD,
                answer="🍎",
                options=["🍎"],
                attempts_left=3,
                created_at=now,
                expires_at=now + datetime.timedelta(minutes=15),
                wave_id=wave.id,
            )
            for user_id in range(10, 10 + held)
        )
        await session.commit()
        return wave.id


async def test_declining_a_wave_from_the_console_declines_its_held_requests(client, db_session_maker, bot) -> None:
    wave_id = await _wave(db_session_maker, held=3)

    async with client:
        response = await client.post(f"/api/signals/waves/{wave_id}/decision", json={"action": "decline"})

    assert response.status_code == 202, response.text
    assert bot.decline_chat_join_request.await_count == 3
    async with db_session_maker() as session:
        wave = await session.get(JoinWave, wave_id)
        assert wave is not None
        assert (wave.decision, wave.decided_by) == (JoinWave.DECISION_DECLINE, ADMIN)
    # The alert in the report chat says what was done, and by whom.
    edited = bot.edit_message_text.await_args.kwargs
    assert (edited["chat_id"], edited["message_id"]) == (-500, 77)
    assert "консоль" in edited["text"]


async def test_a_wave_decided_otherwise_is_not_decided_again(client, db_session_maker, bot) -> None:
    wave_id = await _wave(db_session_maker, held=2, decision=JoinWave.DECISION_RESUME)

    async with client:
        response = await client.post(f"/api/signals/waves/{wave_id}/decision", json={"action": "decline"})

    assert response.status_code == 409
    bot.decline_chat_join_request.assert_not_awaited()


async def test_a_wave_decision_is_one_of_the_three_buttons(client, db_session_maker) -> None:
    wave_id = await _wave(db_session_maker, held=1)

    async with client:
        response = await client.post(f"/api/signals/waves/{wave_id}/decision", json={"action": "approve"})

    assert response.status_code == 422


async def test_an_unknown_wave_is_not_found(client) -> None:
    async with client:
        response = await client.post("/api/signals/waves/999/decision", json={"action": "leave"})

    assert response.status_code == 404


async def _proposal(db_session_maker, *, target: int = 7, chat_id: int | None = -100, expires_in: int = 30) -> int:
    async with db_session_maker() as session:
        session.add(Chat(id=-100, title="Kolej", resource_status=Chat.STATUS_APPROVED))
        session.add(User(id=target, username="promo"))
        proposal = PendingAction(
            origin="mcp",
            initiator_id=ADMIN,
            action="ban",
            target_user_id=target,
            chat_id=chat_id,
            reason="ads",
            expires_at=utc_now() + datetime.timedelta(minutes=expires_in),
        )
        session.add(proposal)
        await session.flush()
        proposal.admin_chat_id = ADMIN
        proposal.admin_message_id = 88
        await session.commit()
        return proposal.id


async def test_confirming_a_proposal_bans_and_names_the_admin_who_pressed(client, db_session_maker, bot) -> None:
    proposal_id = await _proposal(db_session_maker)

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": True})

    assert response.status_code == 200, response.text
    assert response.json() == {"outcome": "confirmed"}
    bot.ban_chat_member.assert_awaited_once_with(-100, 7)
    async with db_session_maker() as session:
        proposal = await session.get(PendingAction, proposal_id)
        assert proposal is not None
        assert (proposal.status, proposal.resolved_by) == (PendingActionStatus.CONFIRMED, ADMIN)
        event = await session.scalar(select(ModerationEvent))
        assert event is not None
        assert (event.action, event.actor_id) == (ModerationEventAction.BAN, ADMIN)
    # The private message's buttons would now do nothing; they go, and it says why.
    edited = bot.edit_message_text.await_args.kwargs
    assert (edited["chat_id"], edited["message_id"], edited["reply_markup"]) == (ADMIN, 88, None)
    assert "консол" in edited["text"]


async def test_rejecting_a_proposal_executes_nothing(client, db_session_maker, bot) -> None:
    proposal_id = await _proposal(db_session_maker)

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": False})

    assert response.json() == {"outcome": "rejected"}
    bot.ban_chat_member.assert_not_awaited()


async def test_a_proposal_already_answered_says_so(client, db_session_maker, bot) -> None:
    proposal_id = await _proposal(db_session_maker, expires_in=-1)

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": True})

    assert response.status_code == 409
    assert response.json()["detail"] == "gone"
    bot.ban_chat_member.assert_not_awaited()


async def test_a_super_admin_is_never_banned_from_the_console(client, db_session_maker, bot) -> None:
    proposal_id = await _proposal(db_session_maker, target=ADMIN)

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": True})

    assert response.status_code == 409
    assert response.json()["detail"] == "protected"
    bot.ban_chat_member.assert_not_awaited()


async def test_a_refusal_from_telegram_closes_the_proposal_as_failed(client, db_session_maker, bot) -> None:
    proposal_id = await _proposal(db_session_maker)
    bot.ban_chat_member.side_effect = RuntimeError("Bad Request: not enough rights")

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": True})

    assert response.status_code == 502
    async with db_session_maker() as session:
        proposal = await session.get(PendingAction, proposal_id)
        assert proposal is not None
        assert proposal.status == PendingActionStatus.FAILED
    assert "Telegram отказал" in bot.edit_message_text.await_args.kwargs["text"]


async def test_a_failure_before_the_claim_leaves_the_bots_message_alone(
    client, db_session_maker, bot, monkeypatch
) -> None:
    from app.moderation.pending_actions import PendingActionService

    proposal_id = await _proposal(db_session_maker)
    monkeypatch.setattr(PendingActionService, "_claim", AsyncMock(side_effect=RuntimeError("database gone")))

    async with client:
        response = await client.post(f"/api/signals/actions/{proposal_id}", json={"confirm": True})

    assert response.status_code == 502
    # Still open, so its buttons still work and nothing says it closed.
    bot.edit_message_text.assert_not_awaited()
    async with db_session_maker() as session:
        proposal = await session.get(PendingAction, proposal_id)
        assert proposal is not None
        assert proposal.status == PendingActionStatus.PENDING


async def test_a_decided_wave_leaves_the_signals_before_the_work_is_done(
    client, db_session_maker, bot, monkeypatch
) -> None:
    from app.webapi.routes import signals

    wave_id = await _wave(db_session_maker, held=2)
    # The declining that follows the answer, held back.
    monkeypatch.setattr(signals, "_decide_wave", AsyncMock())

    async with client:
        decided = await client.post(f"/api/signals/waves/{wave_id}/decision", json={"action": "decline"})
        listed = await client.get("/api/signals")

    assert decided.status_code == 202
    assert listed.json()["waves"] == []
    bot.decline_chat_join_request.assert_not_awaited()
