"""Somebody who tapped to join one of our chats in the Mini App catalog is let in once, without a captcha.

Telegram signed the tap, so it is the proof the captcha asks for. The pass it leaves
is spent by the next join request, expires, and counts towards a wave like trust does.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import service, waves
from app.core.config import CaptchaSettings, settings
from app.core.enums import ModerationEventAction, ModerationEventSource
from app.core.time import utc_now
from app.db.models import CatalogPass, JoinCaptcha, ModerationEvent
from app.db.models import Chat as DbChat
from app.db.models import User as DbUser
from app.presentation.telegram.handlers.events import join_requested
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
OTHER_CHAT_ID = -1001370017011
USER_ID = 4242
NOW = utc_now()


def _request(user_id: int = USER_ID) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=user_id, is_bot=False, first_name="Applicant"),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


@pytest.fixture
async def chat(session: AsyncSession) -> DbChat:
    row = DbChat(
        id=CHAT_ID,
        title="ČVUT FIT",
        resource_status=DbChat.STATUS_APPROVED,
        join_mode=DbChat.JOIN_CAPTCHA,
        public_link="https://t.me/cvut_fit",
    )
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    sent = MagicMock()
    sent.message_id = 77
    tg_bot.send_message = AsyncMock(return_value=sent)
    tg_bot.edit_message_text = AsyncMock()
    tg_bot.approve_chat_join_request = AsyncMock()
    tg_bot.decline_chat_join_request = AsyncMock()
    return tg_bot


async def _settled(
    session: AsyncSession,
    *,
    days_ago: float,
    status: str = JoinCaptcha.STATUS_PASSED,
    chat_id: int = OTHER_CHAT_ID,
    user_id: int = USER_ID,
) -> None:
    """A captcha this person settled in a chat some days ago."""
    at = NOW - datetime.timedelta(days=days_ago)
    row = JoinCaptcha(
        chat_id=chat_id,
        user_id=user_id,
        user_chat_id=user_id,
        status=status,
        answer="🐶",
        options=["🐶"],
        attempts_left=0,
        created_at=at,
        expires_at=at + datetime.timedelta(minutes=15),
    )
    row.resolved_at = at
    session.add(row)
    await session.commit()


async def _latest(session: AsyncSession, user_id: int = USER_ID) -> JoinCaptcha:
    row = (
        await session.scalars(
            select(JoinCaptcha)
            .where(JoinCaptcha.chat_id == CHAT_ID, JoinCaptcha.user_id == user_id)
            .order_by(JoinCaptcha.id.desc())
        )
    ).first()
    assert row is not None
    return row


def _captchas_sent(bot) -> int:
    """Messages with emoji to tap, as opposed to the note with the chat's link."""
    return sum(1 for call in bot.send_message.await_args_list if _asks(call.kwargs.get("reply_markup")))


def _asks(markup) -> bool:
    return markup is not None and any(b.callback_data for row in markup.inline_keyboard for b in row)


def _events(event: str) -> float:
    return REGISTRY.get_sample_value("captcha_events_total", {"event": event}) or 0.0


async def _pass(session: AsyncSession, *, hours: float = 24, user_id: int = USER_ID, chat_id: int = CHAT_ID) -> None:
    session.add(CatalogPass(user_id, chat_id, NOW + datetime.timedelta(hours=hours)))
    await session.commit()


async def _passes(session: AsyncSession) -> int:
    return len((await session.scalars(select(CatalogPass))).all())


def test_a_pass_lasts_a_day_unless_configured() -> None:
    assert CaptchaSettings().catalog_pass_hours == 24


async def test_a_catalog_pass_lets_them_straight_in(session: AsyncSession, bot, chat) -> None:
    caught = _events("catalog")
    await _pass(session)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert _captchas_sent(bot) == 0
    row = await _latest(session)
    assert row.status == JoinCaptcha.STATUS_CATALOG
    assert row.resolved_at == NOW
    assert _events("catalog") == caught + 1


async def test_a_pass_is_spent_by_its_first_request(session: AsyncSession, bot, chat) -> None:
    await _pass(session)

    await service.admit(bot, session, _request(), chat, now=NOW)
    await service.admit(bot, session, _request(), chat, now=NOW + datetime.timedelta(minutes=1))

    assert bot.approve_chat_join_request.await_count == 1
    assert _captchas_sent(bot) == 1
    assert await _passes(session) == 0
    assert (await _latest(session)).status == JoinCaptcha.STATUS_PENDING


async def test_an_expired_pass_asks_again(session: AsyncSession, bot, chat) -> None:
    await _pass(session, hours=-1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


async def test_a_pass_for_another_chat_or_person_does_not_count(session: AsyncSession, bot, chat) -> None:
    await _pass(session, chat_id=OTHER_CHAT_ID)
    await _pass(session, user_id=USER_ID + 1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1
    assert await _passes(session) == 2


async def test_being_let_in_this_way_is_not_a_pass_to_trust(session: AsyncSession, bot, chat) -> None:
    """Or trust would renew from a tap and never need a captcha again."""
    await _pass(session)
    await service.admit(bot, session, _request(), chat, now=NOW)
    other = DbChat(
        id=OTHER_CHAT_ID, title="Other", resource_status=DbChat.STATUS_APPROVED, join_mode=DbChat.JOIN_CAPTCHA
    )
    session.add(other)
    await session.commit()

    assert not await service._trusted(session, OTHER_CHAT_ID, USER_ID, NOW)


async def test_a_ban_on_record_leaves_the_pass_unused(session: AsyncSession, bot, chat) -> None:
    await _pass(session)
    session.add(
        ModerationEvent(
            action=ModerationEventAction.BAN,
            source=ModerationEventSource.COMMAND,
            actor_id=1,
            target_user_id=USER_ID,
            chat_id=OTHER_CHAT_ID,
        )
    )
    await session.commit()

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


async def test_a_blacklisted_applicant_is_declined_whatever_they_tapped(session: AsyncSession, bot, chat) -> None:
    await _pass(session)
    session.add(DbUser(id=USER_ID, username="spammer", blocked=True))
    await session.commit()

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.approve_chat_join_request.assert_not_awaited()


async def test_cross_chat_trust_does_not_spend_the_pass(session: AsyncSession, bot, chat) -> None:
    await _pass(session)
    at = NOW - datetime.timedelta(days=1)
    done = JoinCaptcha(
        chat_id=OTHER_CHAT_ID,
        user_id=USER_ID,
        user_chat_id=USER_ID,
        status=JoinCaptcha.STATUS_PASSED,
        answer="x",
        options=["x"],
        attempts_left=0,
        created_at=at,
        expires_at=at,
    )
    done.resolved_at = at
    session.add(done)
    await session.commit()

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert (await _latest(session)).status == JoinCaptcha.STATUS_TRUSTED
    assert await _passes(session) == 1


async def test_a_pass_is_let_in_during_a_wave(session: AsyncSession, bot, chat) -> None:
    for user_id in range(1, waves.PER_MINUTE + 5):
        await service.admit(bot, session, _request(user_id), chat, now=NOW)
    assert (await _latest(session, waves.PER_MINUTE + 4)).status == JoinCaptcha.STATUS_HELD
    await _pass(session)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert (await _latest(session)).status == JoinCaptcha.STATUS_CATALOG


async def test_requests_on_a_pass_still_count_towards_a_wave(session: AsyncSession, bot, chat) -> None:
    holders = range(1000, 1000 + waves.PER_MINUTE + 1)
    for user_id in holders:
        await _pass(session, user_id=user_id)
        await service.admit(bot, session, _request(user_id), chat, now=NOW)

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert bot.approve_chat_join_request.await_count == len(holders)
    assert (await _latest(session)).status == JoinCaptcha.STATUS_HELD
    report_chat = settings.admin.default_report_chat_id
    alerts = [call for call in bot.send_message.await_args_list if call.kwargs["chat_id"] == report_chat]
    assert len(alerts) == 1


async def test_the_sweep_forgets_passes_past_their_time(session: AsyncSession) -> None:
    await _pass(session, hours=-1)
    await _pass(session, hours=1, user_id=USER_ID + 1)

    await service.forget_old(session, now=NOW)

    left = (await session.scalars(select(CatalogPass))).all()
    assert [p.user_id for p in left] == [USER_ID + 1]
