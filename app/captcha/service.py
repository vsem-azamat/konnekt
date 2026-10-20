"""The join captcha: one private message per applicant, answered by a tap.

Telegram lets a bot write to someone who asked to join for five minutes, and
the captcha lives inside that window: the message goes out with the request
and expires with it. The right emoji approves the request; two wrong ones, or
silence, decline it. A declined applicant is not banned and may ask again.
"""

import asyncio
import datetime
import enum

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.captcha import challenge, waves
from app.captcha.telegram import with_retry
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinCaptcha, JoinWave

logger = get_logger("captcha")

SWEEP_INTERVAL_SECONDS = 15


class Outcome(enum.Enum):
    PASSED = "passed"
    RETRY = "retry"
    FAILED = "failed"
    # Not this person's, already settled, or out of time: nothing changes.
    CLOSED = "closed"
    # Settled by someone else between the message and the tap.
    GONE = "gone"


async def admit(
    bot: Bot, db: AsyncSession, event: ChatJoinRequest, chat: Chat, *, now: datetime.datetime | None = None
) -> None:
    """Send the captcha for a request, unless a wave says to hold or decline it."""
    now = now or utc_now()
    wave = await waves.surge(bot, db, chat, now)
    answer, options = challenge.draw()
    row = JoinCaptcha(
        chat_id=chat.id,
        user_id=event.from_user.id,
        user_chat_id=event.user_chat_id,
        status=JoinCaptcha.STATUS_PENDING,
        answer=answer,
        options=options,
        attempts_left=challenge.ATTEMPTS,
        created_at=now,
        expires_at=now + datetime.timedelta(minutes=challenge.ANSWER_MINUTES),
    )

    if wave is not None and wave.decision != JoinWave.DECISION_RESUME:
        row.wave_id = wave.id
        if wave.decision == JoinWave.DECISION_DECLINE:
            row.status = JoinCaptcha.STATUS_DECLINED
            row.resolved_at = now
            db.add(row)
            await db.commit()
            await with_retry(lambda: bot.decline_chat_join_request(chat_id=chat.id, user_id=event.from_user.id))
            return
        row.status = JoinCaptcha.STATUS_HELD
        db.add(row)
        await db.commit()
        return

    db.add(row)
    await db.commit()
    try:
        sent = await bot.send_message(
            chat_id=event.user_chat_id,
            text=challenge.ask_text(_title(chat), answer),
            reply_markup=challenge.keyboard(row.id, options),
        )
    except TelegramAPIError as err:
        # Usually another bot wrote first, which closes the window. The request
        # stays as it was, for the admins, exactly as without a captcha.
        row.status = JoinCaptcha.STATUS_UNDELIVERED
        row.resolved_at = now
        await db.commit()
        logger.warning("captcha_not_delivered", chat_id=chat.id, user_id=event.from_user.id, error=str(err))
        return
    row.message_id = sent.message_id
    await db.commit()
    logger.info("captcha_sent", chat_id=chat.id, user_id=event.from_user.id, captcha_id=row.id)


async def answer(
    bot: Bot,
    db: AsyncSession,
    *,
    challenge_id: int,
    user_id: int,
    pick: int,
    now: datetime.datetime | None = None,
) -> Outcome:
    """Settle a tap on one of the captcha's buttons."""
    now = now or utc_now()
    row = await db.scalar(select(JoinCaptcha).where(JoinCaptcha.id == challenge_id).with_for_update())
    # The id in the button is not a credential: only the applicant it was sent
    # to may answer it, as with the Mini App check.
    if (
        row is None
        or row.user_id != user_id
        or row.status != JoinCaptcha.STATUS_PENDING
        or now >= row.expires_at
        or not 0 <= pick < len(row.options)
    ):
        return Outcome.CLOSED

    chat = await db.get(Chat, row.chat_id)
    title = _title(chat) if chat else str(row.chat_id)

    # The tap arrives in a private chat, past the gate that stops the bot in
    # chats it does not moderate, so the chat is asked again here: taken off
    # approval or captcha since the message went out, the request is the
    # admins' once more and the bot decides nothing.
    if not _still_checks(chat):
        await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.handed_back_text(title))
        logger.info("captcha_chat_no_longer_checks", captcha_id=row.id, chat_id=row.chat_id)
        return Outcome.GONE

    if row.options[pick] == row.answer:
        try:
            await bot.approve_chat_join_request(chat_id=row.chat_id, user_id=row.user_id)
        except TelegramBadRequest as err:
            if "USER_ALREADY_PARTICIPANT" not in err.message:
                await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.gone_text(title))
                logger.info("captcha_request_gone", captcha_id=row.id, error=str(err))
                return Outcome.GONE
        await _close(
            bot, db, row, JoinCaptcha.STATUS_PASSED, now, challenge.passed_text(title), challenge.open_chat(_link(chat))
        )
        logger.info("captcha_passed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.PASSED

    row.attempts_left -= 1
    if row.attempts_left <= 0:
        await with_retry(lambda: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        await _close(bot, db, row, JoinCaptcha.STATUS_FAILED, now, challenge.failed_text(title))
        logger.info("captcha_failed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.FAILED

    # A fresh board, so that tapping through the options one by one is no strategy.
    row.answer, row.options = challenge.draw()
    await db.commit()
    await _edit(bot, row, challenge.retry_text(title, row.answer), challenge.keyboard(row.id, row.options))
    return Outcome.RETRY


async def expire_stale(bot: Bot, db: AsyncSession, *, now: datetime.datetime | None = None) -> int:
    """Decline every captcha whose time ran out; returns how many."""
    now = now or utc_now()
    stale = (
        await db.scalars(
            select(JoinCaptcha).where(
                JoinCaptcha.status == JoinCaptcha.STATUS_PENDING,
                JoinCaptcha.expires_at <= now,
            )
        )
    ).all()
    for row in stale:
        chat = await db.get(Chat, row.chat_id)
        title = _title(chat) if chat else str(row.chat_id)
        if not _still_checks(chat):
            await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.handed_back_text(title))
            continue
        await with_retry(lambda row=row: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        await _close(bot, db, row, JoinCaptcha.STATUS_EXPIRED, now, challenge.failed_text(title))
    if stale:
        logger.info("captcha_expired", count=len(stale))
    return len(stale)


async def run_sweep(
    session_maker: async_sessionmaker[AsyncSession], bot: Bot, interval_seconds: int = SWEEP_INTERVAL_SECONDS
) -> None:
    """Expire unanswered captchas and keep wave alerts current, for as long as the bot runs."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with session_maker() as session:
                await expire_stale(bot, session)
                await waves.refresh_alerts(bot, session, utc_now())
        except asyncio.CancelledError:
            logger.info("captcha_sweep_cancelled")
            raise
        except Exception:
            logger.exception("captcha_sweep_failed")


async def _close(
    bot: Bot,
    db: AsyncSession,
    row: JoinCaptcha,
    status: str,
    now: datetime.datetime,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    row.status = status
    row.resolved_at = now
    await db.commit()
    await _edit(bot, row, text, markup)


async def _edit(bot: Bot, row: JoinCaptcha, text: str, markup: InlineKeyboardMarkup | None) -> None:
    if row.message_id is None:
        return
    try:
        await bot.edit_message_text(chat_id=row.user_chat_id, message_id=row.message_id, text=text, reply_markup=markup)
    except TelegramAPIError as err:
        # The decision stands either way; the applicant just sees stale buttons.
        logger.warning("captcha_message_not_edited", captcha_id=row.id, error=str(err))


def _still_checks(chat: Chat | None) -> bool:
    """Whether the bot may still decide this chat's requests.

    Asked at every decision, not only when the captcha went out: taps and the
    sweep both run outside the group gate.
    """
    return chat is not None and chat.resource_status == Chat.STATUS_APPROVED and chat.is_captcha_enabled


def _title(chat: Chat) -> str:
    return chat.title or str(chat.id)


def _link(chat: Chat | None) -> str | None:
    return chat.public_link if chat else None
