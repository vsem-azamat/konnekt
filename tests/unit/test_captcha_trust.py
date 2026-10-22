"""Somebody who passed the captcha in another of our chats lately is let in without one.

The captcha proves a person is behind the account. Having proved it in one chat
within `settings.captcha.trust_days`, they are approved in the next straight
away. Only a captcha actually passed counts: being let in on trust does not, or
trust would renew itself forever without anybody tapping anything.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import ApproveChatJoinRequest, SendMessage
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import service, waves
from app.core.config import CaptchaSettings, settings
from app.core.enums import ModerationEventAction, ModerationEventSource
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha, ModerationEvent
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
        is_captcha_enabled=True,
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


def test_trust_lasts_ninety_days_unless_configured() -> None:
    assert CaptchaSettings().trust_days == 90


async def test_a_pass_elsewhere_within_the_window_lets_them_straight_in(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=89)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert _captchas_sent(bot) == 0
    row = await _latest(session)
    assert row.status == JoinCaptcha.STATUS_TRUSTED
    assert row.resolved_at == NOW


async def test_a_trusted_applicant_is_told_they_are_in_with_the_link(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == USER_ID
    assert "Готово" in kwargs["text"]
    assert "ČVUT FIT" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == "https://t.me/cvut_fit"


async def test_a_pass_older_than_the_window_asks_again(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=91)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1
    assert (await _latest(session)).status == JoinCaptcha.STATUS_PENDING


async def test_the_window_comes_from_settings(session: AsyncSession, bot, chat, monkeypatch) -> None:
    monkeypatch.setattr(settings.captcha, "trust_days", 30)
    await _settled(session, days_ago=31)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


async def test_a_pass_in_the_same_chat_does_not_count(session: AsyncSession, bot, chat) -> None:
    """Coming back to a chat they left is asking again; trust is for the next chat."""
    await _settled(session, days_ago=1, chat_id=CHAT_ID)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


@pytest.mark.parametrize(
    "status",
    [
        JoinCaptcha.STATUS_FAILED,
        JoinCaptcha.STATUS_EXPIRED,
        JoinCaptcha.STATUS_DECLINED,
        JoinCaptcha.STATUS_GONE,
        JoinCaptcha.STATUS_UNDELIVERED,
        JoinCaptcha.STATUS_PENDING,
        JoinCaptcha.STATUS_HELD,
        # Let in on trust is not having passed: trust would never run out.
        JoinCaptcha.STATUS_TRUSTED,
    ],
)
async def test_only_a_captcha_actually_passed_counts(session: AsyncSession, bot, chat, status: str) -> None:
    await _settled(session, days_ago=1, status=status)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


async def test_someone_elses_pass_does_not_count(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1, user_id=USER_ID + 1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert _captchas_sent(bot) == 1


async def test_a_blacklisted_applicant_is_declined_whatever_they_passed(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1)
    session.add(DbUser(id=USER_ID, username="spammer", blocked=True))
    await session.commit()

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.approve_chat_join_request.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.parametrize("action", [ModerationEventAction.BAN, ModerationEventAction.BLACKLIST])
@pytest.mark.parametrize("days_ago", [0, 200])
async def test_a_ban_on_record_takes_the_trust_away(
    session: AsyncSession, bot, chat, action: ModerationEventAction, days_ago: int
) -> None:
    """However old, and lifted or not: still banned somewhere is not to be told apart from lifted."""
    await _settled(session, days_ago=10)
    ban = ModerationEvent(
        action=action, source=ModerationEventSource.COMMAND, actor_id=1, target_user_id=USER_ID, chat_id=OTHER_CHAT_ID
    )
    ban.created_at = NOW - datetime.timedelta(days=days_ago)
    session.add(ban)
    await session.commit()

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_not_awaited()
    assert _captchas_sent(bot) == 1


async def test_a_trusted_applicant_is_let_in_during_a_wave(session: AsyncSession, bot, chat) -> None:
    for user_id in range(1, waves.PER_MINUTE + 5):
        await service.admit(bot, session, _request(user_id), chat, now=NOW)
    assert (await _latest(session, waves.PER_MINUTE + 4)).status == JoinCaptcha.STATUS_HELD
    await _settled(session, days_ago=1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert (await _latest(session)).status == JoinCaptcha.STATUS_TRUSTED


async def test_trusted_applicants_still_count_towards_a_wave(session: AsyncSession, bot, chat) -> None:
    """A raid of accounts that each passed once somewhere still raises the alert; they just do not wait."""
    trusted = range(1000, 1000 + waves.PER_MINUTE + 1)
    for user_id in trusted:
        await _settled(session, days_ago=1, user_id=user_id)
        await service.admit(bot, session, _request(user_id), chat, now=NOW)

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert bot.approve_chat_join_request.await_count == len(trusted)
    assert (await _latest(session)).status == JoinCaptcha.STATUS_HELD
    report_chat = settings.admin.default_report_chat_id
    alerts = [call for call in bot.send_message.await_args_list if call.kwargs["chat_id"] == report_chat]
    assert len(alerts) == 1


async def test_a_new_request_after_trust_retires_nothing_it_should_not(session: AsyncSession, bot, chat) -> None:
    """An earlier open captcha in this chat is closed by the trusted request, as by any new one."""
    await service.admit(bot, session, _request(), chat, now=NOW - datetime.timedelta(minutes=1))
    await _settled(session, days_ago=1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    rows = (
        await session.scalars(select(JoinCaptcha).where(JoinCaptcha.chat_id == CHAT_ID, JoinCaptcha.user_id == USER_ID))
    ).all()
    assert sorted(r.status for r in rows) == [JoinCaptcha.STATUS_GONE, JoinCaptcha.STATUS_TRUSTED]


async def test_the_note_goes_out_before_the_approval(session: AsyncSession, bot, chat) -> None:
    """Telegram lets the bot write to an applicant only until the request is settled."""
    await _settled(session, days_ago=1)
    calls = MagicMock()
    calls.attach_mock(bot.send_message, "send")
    calls.attach_mock(bot.approve_chat_join_request, "approve")

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert [name for name, *_ in calls.mock_calls] == ["send", "approve"]


async def test_a_note_that_cannot_be_sent_does_not_keep_them_out(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=USER_ID, text="x"), message="Forbidden: bot can't initiate conversation"
    )

    await service.admit(bot, session, _request(), chat, now=NOW)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert (await _latest(session)).status == JoinCaptcha.STATUS_TRUSTED


async def test_already_a_member_still_counts_as_let_in(session: AsyncSession, bot, chat) -> None:
    trusted = _events("trusted")
    await _settled(session, days_ago=1)
    bot.approve_chat_join_request.side_effect = TelegramBadRequest(
        method=ApproveChatJoinRequest(chat_id=CHAT_ID, user_id=USER_ID), message="Bad Request: USER_ALREADY_PARTICIPANT"
    )

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert (await _latest(session)).status == JoinCaptcha.STATUS_TRUSTED
    assert _events("trusted") == trusted + 1
    bot.edit_message_text.assert_not_awaited()


async def test_a_request_closed_meanwhile_is_gone_and_the_note_says_so(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1)
    bot.approve_chat_join_request.side_effect = TelegramBadRequest(
        method=ApproveChatJoinRequest(chat_id=CHAT_ID, user_id=USER_ID), message="Bad Request: HIDE_REQUESTER_MISSING"
    )

    await service.admit(bot, session, _request(), chat, now=NOW)

    row = await _latest(session)
    assert row.status == JoinCaptcha.STATUS_GONE
    edit = bot.edit_message_text.await_args.kwargs
    assert edit["message_id"] == 77
    assert "Готово" not in edit["text"]


async def test_a_refused_approval_goes_to_the_admins(session: AsyncSession, bot, chat) -> None:
    await _settled(session, days_ago=1)
    bot.approve_chat_join_request.side_effect = TelegramBadRequest(
        method=ApproveChatJoinRequest(chat_id=CHAT_ID, user_id=USER_ID), message="Bad Request: CHAT_ADMIN_REQUIRED"
    )

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert (await _latest(session)).status == JoinCaptcha.STATUS_GONE
    assert "Готово" not in bot.edit_message_text.await_args.kwargs["text"]
    report_chat = settings.admin.default_report_chat_id
    reports = [c.kwargs["text"] for c in bot.send_message.await_args_list if c.kwargs["chat_id"] == report_chat]
    assert len(reports) == 1
    assert "права бота" in reports[0]


async def test_trusted_approvals_are_counted_apart(session: AsyncSession, bot, chat) -> None:
    trusted, passed, sent = _events("trusted"), _events("passed"), _events("sent")
    await _settled(session, days_ago=1)

    await service.admit(bot, session, _request(), chat, now=NOW)

    assert _events("trusted") == trusted + 1
    assert _events("passed") == passed
    assert _events("sent") == sent
