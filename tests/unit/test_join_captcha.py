"""The join captcha: an applicant proves they are a person in a private message.

A chat that takes people by request, with captcha on, gets a message to each
applicant: tap the named emoji within five minutes, two mistakes allowed. Right
answer, the request is approved; out of time or out of tries, declined.

Every applicant is a row, so a restart forgets nobody and the expiry sweep can
close what was left open.
"""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import challenge as challenge_module
from app.captcha import service
from app.captcha.challenge import ATTEMPTS, EMOJI, OPTIONS
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha
from app.db.models import User as DbUser
from app.presentation.telegram.handlers.events import join_requested
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
USER_ID = 4242
NAMES = dict(EMOJI)


def _request(user_id: int = USER_ID) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=user_id, is_bot=False, first_name="Applicant"),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


async def _seed_chat(session: AsyncSession, *, captcha: bool = True, link: str | None = None) -> None:
    session.add(
        DbChat(
            id=CHAT_ID,
            title="ČVUT FIT",
            resource_status=DbChat.STATUS_APPROVED,
            is_captcha_enabled=captcha,
            public_link=link,
        )
    )
    await session.commit()


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    sent = MagicMock()
    sent.message_id = 77
    tg_bot.send_message = AsyncMock(return_value=sent)
    tg_bot.edit_message_text = AsyncMock()
    tg_bot.approve_chat_join_request = AsyncMock()
    tg_bot.decline_chat_join_request = AsyncMock()
    tg_bot.answer_chat_join_request_query = AsyncMock()
    return tg_bot


async def _only_challenge(session: AsyncSession) -> JoinCaptcha:
    rows = (await session.scalars(select(JoinCaptcha))).all()
    assert len(rows) == 1
    return rows[0]


def _wrong_pick(challenge: JoinCaptcha) -> int:
    return next(i for i, emoji in enumerate(challenge.options) if emoji != challenge.answer)


# --- the request -------------------------------------------------------------


async def test_applicant_gets_the_captcha_in_a_private_message(session: AsyncSession, bot) -> None:
    await _seed_chat(session)

    await join_requested(_request(), bot, session)

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    challenge = await _only_challenge(session)
    assert kwargs["chat_id"] == USER_ID
    assert "ČVUT FIT" in kwargs["text"]
    assert NAMES[challenge.answer] in kwargs["text"]
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [b.text for b in buttons] == challenge.options
    assert len(buttons) == OPTIONS
    assert challenge.answer in challenge.options
    assert challenge.status == JoinCaptcha.STATUS_PENDING
    assert challenge.message_id == 77
    bot.approve_chat_join_request.assert_not_awaited()
    bot.decline_chat_join_request.assert_not_awaited()


async def test_chat_without_captcha_leaves_the_request_to_the_admins(session: AsyncSession, bot) -> None:
    await _seed_chat(session, captcha=False)

    await join_requested(_request(), bot, session)

    bot.send_message.assert_not_awaited()
    assert (await session.scalars(select(JoinCaptcha))).all() == []


async def test_blacklisted_applicant_is_declined_not_challenged(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    blocked = DbUser(id=USER_ID, username="spammer")
    blocked.blocked = True
    session.add(blocked)
    await session.commit()

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.send_message.assert_not_awaited()


async def test_an_undeliverable_captcha_leaves_the_request_to_the_admins(session: AsyncSession, bot) -> None:
    """Another bot may have written first, which closes the window; nobody is declined for that."""
    await _seed_chat(session)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=USER_ID, text="x"), message="Forbidden: bot can't initiate conversation"
    )

    await join_requested(_request(), bot, session)

    challenge = await _only_challenge(session)
    assert challenge.status == JoinCaptcha.STATUS_UNDELIVERED
    bot.decline_chat_join_request.assert_not_awaited()


# --- the answer --------------------------------------------------------------


async def test_the_right_emoji_lets_the_applicant_in(session: AsyncSession, bot) -> None:
    await _seed_chat(session, link="https://t.me/cvut_fit")
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.PASSED
    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    edit = bot.edit_message_text.await_args.kwargs
    assert edit["chat_id"] == USER_ID
    assert edit["message_id"] == 77
    assert "Готово" in edit["text"]
    assert edit["reply_markup"].inline_keyboard[0][0].url == "https://t.me/cvut_fit"
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_PASSED


async def test_one_mistake_is_forgiven_with_a_fresh_board(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=_wrong_pick(challenge)
    )

    assert outcome is service.Outcome.RETRY
    bot.decline_chat_join_request.assert_not_awaited()
    await session.refresh(challenge)
    assert challenge.attempts_left == ATTEMPTS - 1
    edit = bot.edit_message_text.await_args.kwargs
    assert NAMES[challenge.answer] in edit["text"]
    assert [b.text for row in edit["reply_markup"].inline_keyboard for b in row] == challenge.options


async def test_two_mistakes_decline_the_request(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    for _ in range(ATTEMPTS):
        await session.refresh(challenge)
        outcome = await service.answer(
            bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=_wrong_pick(challenge)
        )

    assert outcome is service.Outcome.FAILED
    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.approve_chat_join_request.assert_not_awaited()
    assert "отклонена" in bot.edit_message_text.await_args.kwargs["text"]


async def test_a_press_by_someone_else_changes_nothing(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID + 1, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.CLOSED
    bot.approve_chat_join_request.assert_not_awaited()


async def test_a_late_press_does_not_let_anyone_in(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    outcome = await service.answer(
        bot,
        session,
        challenge_id=challenge.id,
        user_id=USER_ID,
        pick=challenge.options.index(challenge.answer),
        now=utc_now() + datetime.timedelta(minutes=6),
    )

    assert outcome is service.Outcome.CLOSED
    bot.approve_chat_join_request.assert_not_awaited()


async def test_a_request_closed_meanwhile_is_reported_not_approved_twice(session: AsyncSession, bot) -> None:
    """An admin may have declined it by hand while the applicant was choosing."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.approve_chat_join_request.side_effect = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: HIDE_REQUESTER_MISSING"
    )

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.GONE
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_GONE


# --- the sweep ---------------------------------------------------------------


async def test_an_unanswered_captcha_is_declined_once_its_time_is_up(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    assert await service.expire_stale(bot, session, now=utc_now() + datetime.timedelta(minutes=4)) == 0
    bot.decline_chat_join_request.assert_not_awaited()

    assert await service.expire_stale(bot, session, now=utc_now() + datetime.timedelta(minutes=6)) == 1
    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    assert "отклонена" in bot.edit_message_text.await_args.kwargs["text"]
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_EXPIRED


@pytest.mark.parametrize("change", ["unapproved", "captcha_off"])
async def test_a_tap_after_the_chat_stopped_using_captcha_lets_nobody_in(
    session: AsyncSession, bot, change: str
) -> None:
    """Taps arrive in a private chat, past the group gate: the chat is checked again here."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    if change == "unapproved":
        chat.resource_status = DbChat.STATUS_DISABLED
    else:
        chat.is_captcha_enabled = False
    await session.commit()

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.GONE
    bot.approve_chat_join_request.assert_not_awaited()
    bot.decline_chat_join_request.assert_not_awaited()
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_GONE


async def test_the_sweep_declines_nothing_in_a_chat_that_stopped_using_captcha(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    chat.is_captcha_enabled = False
    await session.commit()

    await service.expire_stale(bot, session, now=utc_now() + datetime.timedelta(minutes=6))

    bot.decline_chat_join_request.assert_not_awaited()
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_GONE


# --- review: every way a request can already be settled ------------------------


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=f"Bad Request: {message}")


def _report_lines(bot) -> list[str]:
    report_chat = settings.admin.default_report_chat_id
    return [c.kwargs["text"] for c in bot.send_message.await_args_list if c.kwargs["chat_id"] == report_chat]


async def test_a_second_tap_after_passing_changes_nothing(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    right = challenge.options.index(challenge.answer)

    await service.answer(bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=right)
    again = await service.answer(bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=right)

    assert again is service.Outcome.CLOSED
    bot.approve_chat_join_request.assert_awaited_once()


@pytest.mark.parametrize("pick", [-1, OPTIONS])
async def test_a_pick_off_the_board_is_ignored(session: AsyncSession, bot, pick: int) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    outcome = await service.answer(bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=pick)

    assert outcome is service.Outcome.CLOSED
    await session.refresh(challenge)
    assert challenge.attempts_left == ATTEMPTS


async def test_already_a_member_counts_as_passing(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.approve_chat_join_request.side_effect = _bad_request("USER_ALREADY_PARTICIPANT")

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.PASSED


async def test_a_refusal_other_than_a_closed_request_is_reported_to_the_admins(session: AsyncSession, bot) -> None:
    """Lost rights are not "the admins already decided": the admins have to be told."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.approve_chat_join_request.side_effect = _bad_request("CHAT_ADMIN_REQUIRED")

    outcome = await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    assert outcome is service.Outcome.GONE
    assert "рассмотрят админы" in bot.edit_message_text.await_args.kwargs["text"]
    assert any("CHAT_ADMIN_REQUIRED" in line for line in _report_lines(bot))


async def test_a_wrong_tap_draws_a_new_board(session: AsyncSession, bot, monkeypatch) -> None:
    boards = iter(
        [
            ("🐱", ["🐱", "🐶", "🍕", "🍎", "🍌", "🚲", "🚗", "🎸"]),
            ("🔑", ["🔑", "⚽", "🌵", "🐟", "🎁", "☕", "📚", "🏠"]),
        ]
    )
    monkeypatch.setattr(challenge_module, "draw", lambda: next(boards))
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    row = await _only_challenge(session)

    await service.answer(bot, session, challenge_id=row.id, user_id=USER_ID, pick=1)

    await session.refresh(row)
    assert row.answer == "🔑"
    assert row.options[0] == "🔑"


async def test_a_new_request_retires_the_old_captcha(session: AsyncSession, bot) -> None:
    """Telegram keeps one request per person: the old buttons must not settle the new one."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    await join_requested(_request(), bot, session)

    rows = (await session.scalars(select(JoinCaptcha).order_by(JoinCaptcha.id))).all()
    assert [r.status for r in rows] == [JoinCaptcha.STATUS_GONE, JoinCaptcha.STATUS_PENDING]
    old = await service.answer(
        bot, session, challenge_id=rows[0].id, user_id=USER_ID, pick=rows[0].options.index(rows[0].answer)
    )
    assert old is service.Outcome.CLOSED
    bot.approve_chat_join_request.assert_not_awaited()


async def test_an_undelivered_captcha_is_reported(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    report_chat = settings.admin.default_report_chat_id

    async def send(chat_id: int, **_: object) -> MagicMock:
        if chat_id != report_chat:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden")
        return MagicMock(message_id=1)

    bot.send_message.side_effect = send

    await join_requested(_request(), bot, session)

    assert any("не дошла" in line for line in _report_lines(bot))


async def test_the_sweep_does_not_tell_an_admitted_member_they_were_declined(session: AsyncSession, bot) -> None:
    """An admin approved the request by hand; the sweep's decline finds nothing to decline."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.decline_chat_join_request.side_effect = _bad_request("HIDE_REQUESTER_MISSING")

    await service.expire_stale(bot, session, now=utc_now() + datetime.timedelta(minutes=6))

    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_GONE
    assert "отклонена" not in bot.edit_message_text.await_args.kwargs["text"]


async def test_old_settled_captchas_are_forgotten(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    long_ago = utc_now() - datetime.timedelta(days=service.RETENTION_DAYS + 1)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    await service.admit(bot, session, _request(), chat, now=long_ago)
    await service.expire_stale(bot, session, now=long_ago + datetime.timedelta(minutes=6))
    await join_requested(_request(USER_ID + 1), bot, session)

    await service.forget_old(session)

    rows = (await session.scalars(select(JoinCaptcha))).all()
    assert [r.user_id for r in rows] == [USER_ID + 1]


async def test_the_sweep_loop_expires_refreshes_and_forgets(monkeypatch) -> None:
    calls: list[str] = []
    sleeps = iter([None])

    async def sleep(_: float) -> None:
        if next(sleeps, "stop") == "stop":
            raise asyncio.CancelledError

    async def expire(*_: object, **__: object) -> int:
        calls.append("expire")
        return 0

    async def refresh(*_: object, **__: object) -> None:
        calls.append("refresh")

    async def forget(*_: object, **__: object) -> None:
        calls.append("forget")

    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    monkeypatch.setattr(service, "expire_stale", expire)
    monkeypatch.setattr(service.waves, "refresh_alerts", refresh)
    monkeypatch.setattr(service, "forget_old", forget)
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(asyncio.CancelledError):
        await service.run_sweep(session_maker, MagicMock(), interval_seconds=0)

    assert calls == ["expire", "refresh", "forget"]
