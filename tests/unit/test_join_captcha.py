"""The join captcha: an applicant proves they are a person in a private message.

A chat that takes people by request, with captcha on, gets a message to each
applicant: tap the named emoji within the answer window, two mistakes allowed. Right
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
from app.core.config import CaptchaSettings, settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha
from app.db.models import User as DbUser
from app.presentation.telegram.handlers.events import join_requested
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
USER_ID = 4242
NAMES = dict(EMOJI)
WINDOW = datetime.timedelta(minutes=settings.captcha.answer_minutes)
INSIDE_WINDOW = WINDOW - datetime.timedelta(minutes=1)
PAST_WINDOW = WINDOW + datetime.timedelta(minutes=1)
REMIND_AFTER = datetime.timedelta(minutes=settings.captcha.remind_after_minutes)


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
            join_mode=DbChat.JOIN_CAPTCHA if captcha else DbChat.JOIN_ADMINS,
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
    assert kwargs["text"] == (
        "🔐 Проверка для чата <b>ČVUT FIT</b>\n\n"
        f"Нажми на <b>{NAMES[challenge.answer].upper()}</b>, и заявку примут.\n\n"
        f"⏱ {settings.captcha.answer_minutes} минут."
    )
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [b.text for b in buttons] == challenge.options
    assert len(buttons) == OPTIONS
    assert challenge.answer in challenge.options
    assert challenge.status == JoinCaptcha.STATUS_PENDING
    assert challenge.message_id == 77
    bot.approve_chat_join_request.assert_not_awaited()
    bot.decline_chat_join_request.assert_not_awaited()


def test_the_answer_window_is_fifteen_minutes_unless_configured() -> None:
    assert CaptchaSettings().answer_minutes == 15


async def test_the_captcha_gives_as_long_as_configured_and_says_so(session: AsyncSession, bot, monkeypatch) -> None:
    monkeypatch.setattr(settings.captcha, "answer_minutes", 21)
    await _seed_chat(session)

    await join_requested(_request(), bot, session)

    challenge = await _only_challenge(session)
    assert challenge.expires_at - challenge.created_at == datetime.timedelta(minutes=21)
    assert "⏱ 21 минута." in bot.send_message.await_args.kwargs["text"]


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
    assert edit["text"] == '✅ Готово, ты в <a href="https://t.me/cvut_fit">ČVUT FIT</a>!'
    assert edit["reply_markup"] is None
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_PASSED


async def test_one_mistake_is_forgiven_and_the_message_stays_as_it_was(session: AsyncSession, bot) -> None:
    """The applicant is told in a popup that goes by itself; the question they are reading does not change."""
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
    bot.edit_message_text.assert_not_awaited()


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
        now=utc_now() + PAST_WINDOW,
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

    assert await service.expire_stale(bot, session, now=utc_now() + INSIDE_WINDOW) == 0
    bot.decline_chat_join_request.assert_not_awaited()

    assert await service.expire_stale(bot, session, now=utc_now() + PAST_WINDOW) == 1
    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert "время вышло" in text
    assert "проверка не пройдена" not in text
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
        chat.join_mode = DbChat.JOIN_ADMINS
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
    chat.join_mode = DbChat.JOIN_ADMINS
    await session.commit()

    await service.expire_stale(bot, session, now=utc_now() + PAST_WINDOW)

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


async def test_a_wrong_tap_keeps_the_answer_the_message_names(session: AsyncSession, bot) -> None:
    """A fresh board would name an answer the unchanged message does not."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    row = await _only_challenge(session)
    answer, options = row.answer, list(row.options)

    await service.answer(bot, session, challenge_id=row.id, user_id=USER_ID, pick=_wrong_pick(row))

    await session.refresh(row)
    assert (row.answer, row.options) == (answer, options)


# --- after passing: Konnekt in the private chat --------------------------------


@pytest.fixture
def intro(bot, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What happened in order: the introduction, the approval, the edit."""
    steps: list[str] = []
    monkeypatch.setattr(settings.telegram, "intro_video", "video-file-id")
    monkeypatch.setattr(settings.webapi, "public_url", "https://konnekt.example")
    bot.send_video = AsyncMock(side_effect=lambda **_: steps.append("video"))
    bot.approve_chat_join_request.side_effect = lambda **_: steps.append("approve")
    bot.edit_message_text.side_effect = lambda **_: steps.append("edit")
    return steps


async def _pass(session: AsyncSession, bot, *, after: datetime.timedelta = datetime.timedelta(0)) -> None:
    await _seed_chat(session, link="https://t.me/cvut_fit")
    await join_requested(_request(), bot, session)
    row = await _only_challenge(session)
    await service.answer(
        bot,
        session,
        challenge_id=row.id,
        user_id=USER_ID,
        pick=row.options.index(row.answer),
        now=row.created_at + after,
    )


async def test_passing_brings_the_konnekt_video_before_the_approval(session: AsyncSession, bot, intro) -> None:
    """Telegram lets the bot write to an applicant only until the request is settled."""
    await _pass(session, bot)

    assert intro == ["video", "approve", "edit"]
    sent = bot.send_video.await_args.kwargs
    assert sent["chat_id"] == USER_ID
    assert sent["video"] == "video-file-id"
    assert sent["caption"] == "👋 Это Konnekt: чаты других факультетов и общежитий и люди, которые помогут с учёбой."
    [[button]] = sent["reply_markup"].inline_keyboard
    assert button.text == "Открыть Konnekt 📱"
    assert button.web_app.url == "https://konnekt.example/chats"


async def test_without_a_video_the_introduction_is_text(session: AsyncSession, bot, intro, monkeypatch) -> None:
    monkeypatch.setattr(settings.telegram, "intro_video", "")

    await _pass(session, bot)

    bot.send_video.assert_not_awaited()
    texts = [c.kwargs["text"] for c in bot.send_message.await_args_list]
    assert texts[-1].startswith("👋 Это Konnekt")


async def test_an_introduction_that_fails_does_not_hold_up_the_approval(session: AsyncSession, bot, intro) -> None:
    bot.send_video.side_effect = TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user")

    await _pass(session, bot)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    row = await _only_challenge(session)
    assert row.status == JoinCaptcha.STATUS_PASSED


async def test_no_introduction_once_telegram_no_longer_lets_the_bot_write(session: AsyncSession, bot, intro) -> None:
    await _pass(session, bot, after=datetime.timedelta(minutes=6))

    assert intro == ["approve", "edit"]


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


async def test_undelivered_captchas_are_summed_up_not_reported_one_by_one(session: AsyncSession, bot) -> None:
    """A second captcha bot in the chat makes every request fail: one line per chat, not per request."""
    await _seed_chat(session)
    report_chat = settings.admin.default_report_chat_id

    async def send(chat_id: int, **_: object) -> MagicMock:
        if chat_id != report_chat:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text="x"), message="Forbidden")
        return MagicMock(message_id=1)

    bot.send_message.side_effect = send
    start = utc_now() - datetime.timedelta(seconds=1)
    for user_id in range(USER_ID, USER_ID + 3):
        await join_requested(_request(user_id), bot, session)
    assert _report_lines(bot) == []

    await service.report_undelivered(bot, session, since=start, until=utc_now() + datetime.timedelta(seconds=1))

    lines = _report_lines(bot)
    assert len(lines) == 1
    assert "ČVUT FIT: 3" in lines[0]


async def test_the_sweep_does_not_tell_an_admitted_member_they_were_declined(session: AsyncSession, bot) -> None:
    """An admin approved the request by hand; the sweep's decline finds nothing to decline."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.decline_chat_join_request.side_effect = _bad_request("HIDE_REQUESTER_MISSING")

    await service.expire_stale(bot, session, now=utc_now() + PAST_WINDOW)

    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_GONE
    assert "отклонена" not in bot.edit_message_text.await_args.kwargs["text"]


async def test_old_settled_captchas_are_forgotten(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    long_ago = utc_now() - datetime.timedelta(days=service.RETENTION_DAYS + 1)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    await service.admit(bot, session, _request(), chat, now=long_ago)
    await service.expire_stale(bot, session, now=long_ago + PAST_WINDOW)
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

    async def remind(*_: object, **__: object) -> None:
        calls.append("remind")

    async def refresh(*_: object, **__: object) -> None:
        calls.append("refresh")

    async def forget(*_: object, **__: object) -> None:
        calls.append("forget")

    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    monkeypatch.setattr(service, "expire_stale", expire)
    monkeypatch.setattr(service, "remind", remind)
    monkeypatch.setattr(service.waves, "refresh_alerts", refresh)
    monkeypatch.setattr(service, "forget_old", forget)
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(asyncio.CancelledError):
        await service.run_sweep(session_maker, MagicMock(), interval_seconds=0)

    assert calls == ["expire", "remind", "refresh", "forget"]


# --- the reminder ------------------------------------------------------------


def test_the_reminder_comes_while_telegram_still_lets_the_bot_write() -> None:
    assert CaptchaSettings().remind_after_minutes == 4
    with pytest.raises(ValidationError):
        CaptchaSettings(remind_after_minutes=5)


def test_the_answer_window_outlasts_the_reminder() -> None:
    with pytest.raises(ValidationError):
        CaptchaSettings(answer_minutes=4, remind_after_minutes=4)


async def test_an_unanswered_captcha_is_reminded_once_with_the_time_left(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER - datetime.timedelta(seconds=1))
    assert bot.send_message.await_count == 1

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=10))
    assert bot.send_message.await_count == 2
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == USER_ID
    left = settings.captcha.answer_minutes - settings.captcha.remind_after_minutes
    answer = challenge_module.NOMINATIVE[challenge.answer].upper()
    assert (
        kwargs["text"]
        == f"⏳ Ещё {left} минут — <b>{answer}</b> {challenge_module.waits(challenge.answer)} в сообщении выше."
    )
    assert kwargs["reply_parameters"].message_id == 77

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=30))
    assert bot.send_message.await_count == 2


async def test_the_time_left_is_rounded_up_and_spelled_right(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    challenge.expires_at = challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=30)
    await session.commit()

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER)

    assert "Ещё 1 минута —" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.parametrize("change", ["unapproved", "captcha_off"])
async def test_no_reminder_once_the_chat_stopped_using_captcha(session: AsyncSession, bot, change: str) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    if change == "unapproved":
        chat.resource_status = DbChat.STATUS_OBSERVED
    else:
        chat.join_mode = DbChat.JOIN_ADMINS
    await session.commit()

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=10))

    assert bot.send_message.await_count == 1


async def test_an_answered_captcha_is_not_reminded(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )
    sent = bot.send_message.await_count

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=10))

    assert bot.send_message.await_count == sent


async def test_no_reminder_once_telegram_no_longer_lets_the_bot_write(session: AsyncSession, bot) -> None:
    """The sweep was down past the five minutes, say for a restart: the message would be refused."""
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    await service.remind(bot, session, now=challenge.created_at + datetime.timedelta(minutes=5))

    assert bot.send_message.await_count == 1


async def test_a_reminder_telegram_refuses_is_not_tried_again(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=USER_ID, text="x"), message="Forbidden: bot was blocked by the user"
    )
    reminded = _events("reminded")

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=10))
    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=30))

    assert bot.send_message.await_count == 2
    await session.refresh(challenge)
    assert challenge.status == JoinCaptcha.STATUS_PENDING
    assert _events("reminded") == reminded


async def test_a_reminder_is_counted(session: AsyncSession, bot) -> None:
    reminded = _events("reminded")
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)

    await service.remind(bot, session, now=challenge.created_at + REMIND_AFTER + datetime.timedelta(seconds=10))

    assert _events("reminded") == reminded + 1


# --- second review -------------------------------------------------------------


async def test_the_retired_captcha_says_so(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    await join_requested(_request(), bot, session)

    texts = [c.kwargs["text"] for c in bot.edit_message_text.await_args_list]
    assert any("больше не действует" in t for t in texts)


async def test_a_held_request_is_retired_by_a_new_one_too(session: AsyncSession, bot) -> None:
    from app.captcha import waves

    await _seed_chat(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    now = utc_now()
    for user_id in range(1, waves.PER_MINUTE + 2):
        await service.admit(bot, session, _request(user_id), chat, now=now)
    last = waves.PER_MINUTE + 1
    await service.admit(bot, session, _request(last), chat, now=now)

    rows = (
        await session.scalars(select(JoinCaptcha).where(JoinCaptcha.user_id == last).order_by(JoinCaptcha.id))
    ).all()
    assert [r.status for r in rows] == [JoinCaptcha.STATUS_GONE, JoinCaptcha.STATUS_HELD]


async def test_retention_keeps_what_is_not_settled(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    chat = await session.get(DbChat, CHAT_ID)
    assert chat is not None
    long_ago = utc_now() - datetime.timedelta(days=service.RETENTION_DAYS + 1)
    await service.admit(bot, session, _request(), chat, now=long_ago)

    await service.forget_old(session)

    assert len((await session.scalars(select(JoinCaptcha))).all()) == 1


async def test_the_sweep_keeps_what_it_settled_before_a_failure(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(USER_ID), bot, session)
    await join_requested(_request(USER_ID + 1), bot, session)
    bot.decline_chat_join_request.side_effect = [None, RuntimeError("connection reset")]

    with pytest.raises(RuntimeError):
        await service.expire_stale(bot, session, now=utc_now() + PAST_WINDOW)
    await session.rollback()

    statuses = [r.status for r in (await session.scalars(select(JoinCaptcha).order_by(JoinCaptcha.id))).all()]
    assert statuses == [JoinCaptcha.STATUS_EXPIRED, JoinCaptcha.STATUS_PENDING]


async def test_a_refusal_that_is_not_about_rights_is_not_blamed_on_them(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    bot.approve_chat_join_request.side_effect = _bad_request("PEER_ID_INVALID")

    await service.answer(
        bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=challenge.options.index(challenge.answer)
    )

    line = _report_lines(bot)[-1]
    assert "Проверьте права" not in line
    assert "Telegram не ответил" in line


# --- what Prometheus is told -------------------------------------------------


def _events(event: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("captcha_events_total", {"event": event}) or 0.0


async def test_the_captcha_counts_what_happens_to_applicants(session: AsyncSession, bot) -> None:
    sent, retry, failed, passed = _events("sent"), _events("retry"), _events("failed"), _events("passed")
    await _seed_chat(session)
    await join_requested(_request(), bot, session)
    challenge = await _only_challenge(session)
    assert _events("sent") == sent + 1

    await service.answer(bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=_wrong_pick(challenge))
    assert _events("retry") == retry + 1
    await session.refresh(challenge)
    await service.answer(bot, session, challenge_id=challenge.id, user_id=USER_ID, pick=_wrong_pick(challenge))
    assert _events("failed") == failed + 1

    await join_requested(_request(USER_ID + 1), bot, session)
    second = (await session.scalars(select(JoinCaptcha).where(JoinCaptcha.user_id == USER_ID + 1))).one()
    await service.answer(
        bot, session, challenge_id=second.id, user_id=USER_ID + 1, pick=second.options.index(second.answer)
    )
    assert _events("passed") == passed + 1


async def test_undelivered_and_expired_captchas_are_counted_too(session: AsyncSession, bot) -> None:
    undelivered, expired = _events("undelivered"), _events("expired")
    await _seed_chat(session)
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=USER_ID, text="x"), message="Forbidden: bot can't initiate conversation"
    )
    await join_requested(_request(), bot, session)
    assert _events("undelivered") == undelivered + 1

    bot.send_message.side_effect = None
    await join_requested(_request(USER_ID + 1), bot, session)
    await service.expire_stale(bot, session, now=utc_now() + PAST_WINDOW)
    assert _events("expired") == expired + 1


# --- the words -------------------------------------------------------------------


def test_every_answer_can_be_named_as_the_subject_too() -> None:
    assert set(challenge_module.NOMINATIVE) == set(NAMES)


def test_the_reminder_agrees_with_an_answer_in_the_plural() -> None:
    assert challenge_module.reminder_text("📚", 3) == "⏳ Ещё 3 минуты — <b>КНИГИ</b> ждут в сообщении выше."
    assert "<b>КОШКА</b> ждёт" in challenge_module.reminder_text("🐱", 3)
