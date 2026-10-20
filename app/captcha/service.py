"""The join captcha: one private message per applicant, answered by a tap.

Telegram lets a bot write to someone who asked to join for five minutes, and
the captcha lives inside that window: the message goes out with the request
and expires with it. The right emoji approves the request; two wrong ones, or
silence, decline it. A declined applicant is not banned and may ask again.

Every decision locks its row, so a tap and the expiry sweep cannot both act on
one request: whichever comes second finds it settled.
"""

import asyncio
import datetime
import enum
import html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.captcha import challenge, waves
from app.captcha.telegram import already_member, report, request_gone, with_retry
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinCaptcha, JoinWave

logger = get_logger("captcha")

SWEEP_INTERVAL_SECONDS = 15
# As long as what people wrote is kept (#174), and swept as rarely.
RETENTION_DAYS = 180
_RETENTION_EVERY = datetime.timedelta(hours=6)


class Outcome(enum.Enum):
    PASSED = "passed"
    RETRY = "retry"
    FAILED = "failed"
    # Not this person's, already settled, or out of time: nothing changes.
    CLOSED = "closed"
    # Settled by someone else between the message and the tap, or no longer ours to settle.
    GONE = "gone"


async def admit(
    bot: Bot, db: AsyncSession, event: ChatJoinRequest, chat: Chat, *, now: datetime.datetime | None = None
) -> None:
    """Send the captcha for a request, unless a wave says to hold or decline it."""
    now = now or utc_now()
    user_id = event.from_user.id

    # One request at a time per chat from the count to the insert: without it a
    # burst counts itself short and opens a wave per handful of requests.
    await _lock_chat(db, chat.id)
    superseded = await _supersede(db, chat.id, user_id, now)
    wave, opened = await waves.surge(db, chat, user_id, now)
    answer, options = challenge.draw()
    row = JoinCaptcha(
        chat_id=chat.id,
        user_id=user_id,
        user_chat_id=event.user_chat_id,
        status=JoinCaptcha.STATUS_PENDING,
        answer=answer,
        options=options,
        attempts_left=challenge.ATTEMPTS,
        created_at=now,
        expires_at=now + datetime.timedelta(minutes=challenge.ANSWER_MINUTES),
    )
    if waves.pauses(wave):
        assert wave is not None
        row.wave_id = wave.id
        row.status = JoinCaptcha.STATUS_HELD
    db.add(row)
    await db.commit()

    for old in superseded:
        await _edit(bot, old, challenge.superseded_text(_title(chat)), None)
    if opened:
        assert wave is not None
        await waves.announce(bot, db, wave, chat)

    if row.status == JoinCaptcha.STATUS_HELD:
        assert wave is not None
        if wave.decision == JoinWave.DECISION_DECLINE:
            await _decline_on_sight(bot, db, row, now)
        return

    try:
        sent = await with_retry(
            lambda: bot.send_message(
                chat_id=event.user_chat_id,
                text=challenge.ask_text(_title(chat), answer),
                reply_markup=challenge.keyboard(row.id, options),
            )
        )
    except TelegramAPIError as err:
        # Usually another bot wrote first, which closes the window. The request
        # stays as it was, for the admins, exactly as without a captcha.
        row.status = JoinCaptcha.STATUS_UNDELIVERED
        row.resolved_at = now
        await db.commit()
        logger.warning("captcha_not_delivered", chat_id=chat.id, user_id=user_id, error=str(err))
        await report(
            bot,
            f"Капча не дошла до заявителя в {html.escape(_title(chat))} ({user_id}): {html.escape(err.message)}. "
            f"Заявка ждёт админов чата.",
        )
        return
    row.message_id = sent.message_id
    await db.commit()
    logger.info("captcha_sent", chat_id=chat.id, user_id=user_id, captcha_id=row.id)


async def _lock_chat(db: AsyncSession, chat_id: int) -> None:
    """Serialise admissions to one chat until the transaction ends.

    PostgreSQL only; the test database runs one request at a time anyway.
    """
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": chat_id})


async def _supersede(db: AsyncSession, chat_id: int, user_id: int, now: datetime.datetime) -> list[JoinCaptcha]:
    """Close this person's earlier captcha for the chat: a new request replaces the old one.

    Telegram keeps one request per person and chat, so an approve or decline
    meant for the old request would land on the new one.
    """
    old = (
        await db.scalars(
            select(JoinCaptcha).where(
                JoinCaptcha.chat_id == chat_id,
                JoinCaptcha.user_id == user_id,
                JoinCaptcha.status.in_((JoinCaptcha.STATUS_PENDING, JoinCaptcha.STATUS_HELD)),
            )
        )
    ).all()
    for row in old:
        row.status = JoinCaptcha.STATUS_GONE
        row.resolved_at = now
    return list(old)


async def _decline_on_sight(bot: Bot, db: AsyncSession, row: JoinCaptcha, now: datetime.datetime) -> None:
    """A request arriving in a wave an admin declined: declined too, if the chat still wants that."""
    chat = await db.get(Chat, row.chat_id)
    if not _still_checks(chat):
        return
    try:
        await with_retry(lambda: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
    except TelegramAPIError as err:
        if not request_gone(err):
            # Stays held: the alert's button declines what is left.
            logger.warning("captcha_wave_decline_failed", captcha_id=row.id, error=str(err))
            return
        row.status = JoinCaptcha.STATUS_GONE
    else:
        row.status = JoinCaptcha.STATUS_DECLINED
    row.resolved_at = now
    await db.commit()


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
        await db.rollback()
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
            await with_retry(lambda: bot.approve_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        except TelegramAPIError as err:
            if not already_member(err):
                return await _refused(bot, db, row, now, title, err, verb="принять")
        await _close(
            bot, db, row, JoinCaptcha.STATUS_PASSED, now, challenge.passed_text(title), challenge.open_chat(_link(chat))
        )
        logger.info("captcha_passed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.PASSED

    row.attempts_left -= 1
    if row.attempts_left <= 0:
        try:
            await with_retry(lambda: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        except TelegramAPIError as err:
            return await _refused(bot, db, row, now, title, err, verb="отклонить")
        await _close(bot, db, row, JoinCaptcha.STATUS_FAILED, now, challenge.failed_text(title))
        logger.info("captcha_failed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.FAILED

    # A fresh board, so that tapping through the options one by one is no strategy.
    row.answer, row.options = challenge.draw()
    await db.commit()
    await _edit(bot, row, challenge.retry_text(title, row.answer), challenge.keyboard(row.id, row.options))
    return Outcome.RETRY


async def _refused(
    bot: Bot,
    db: AsyncSession,
    row: JoinCaptcha,
    now: datetime.datetime,
    title: str,
    err: TelegramAPIError,
    *,
    verb: str,
) -> Outcome:
    """Telegram would not settle the request: closed by somebody else, or the bot cannot."""
    if request_gone(err):
        await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.gone_text(title))
        logger.info("captcha_request_gone", captcha_id=row.id)
        return Outcome.GONE
    # Lost rights, most likely: nothing the applicant can fix, and something the admins must.
    await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.handed_back_text(title))
    logger.warning("captcha_request_refused", captcha_id=row.id, chat_id=row.chat_id, error=str(err))
    await report(
        bot,
        f"Капча не смогла {verb} заявку в {html.escape(title)} ({row.user_id}): {html.escape(err.message)}. "
        f"Проверьте права бота в чате.",
    )
    return Outcome.GONE


async def expire_stale(bot: Bot, db: AsyncSession, *, now: datetime.datetime | None = None) -> int:
    """Decline every captcha whose time ran out; returns how many were looked at.

    Rows a tap is settling right now are locked and skipped: the tap decides
    them, and the next sweep finds them closed.
    """
    now = now or utc_now()
    stale = (
        await db.scalars(
            select(JoinCaptcha)
            .where(JoinCaptcha.status == JoinCaptcha.STATUS_PENDING, JoinCaptcha.expires_at <= now)
            .with_for_update(skip_locked=True)
        )
    ).all()
    closing: list[tuple[JoinCaptcha, str]] = []
    for row in stale:
        chat = await db.get(Chat, row.chat_id)
        title = _title(chat) if chat else str(row.chat_id)
        if not _still_checks(chat):
            row.status, note = JoinCaptcha.STATUS_GONE, challenge.handed_back_text(title)
        else:
            try:
                await with_retry(
                    lambda row=row: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id)
                )
            except TelegramAPIError as err:
                # Settled by an admin meanwhile, or not ours to settle any more:
                # either way the applicant must not be told "declined".
                if request_gone(err):
                    row.status, note = JoinCaptcha.STATUS_GONE, challenge.gone_text(title)
                else:
                    row.status, note = JoinCaptcha.STATUS_GONE, challenge.handed_back_text(title)
                    logger.warning("captcha_expiry_refused", captcha_id=row.id, error=str(err))
            else:
                row.status, note = JoinCaptcha.STATUS_EXPIRED, challenge.failed_text(title)
        row.resolved_at = now
        closing.append((row, note))
    await db.commit()
    for row, note in closing:
        await _edit(bot, row, note, None)
    if stale:
        logger.info("captcha_expired", count=len(stale))
    return len(stale)


async def forget_old(db: AsyncSession, *, now: datetime.datetime | None = None) -> None:
    """Drop settled captchas and waves past the retention period."""
    cutoff = (now or utc_now()) - datetime.timedelta(days=RETENTION_DAYS)
    await db.execute(delete(JoinCaptcha).where(JoinCaptcha.created_at < cutoff, JoinCaptcha.resolved_at.is_not(None)))
    await db.execute(delete(JoinWave).where(JoinWave.last_surge_at < cutoff))
    await db.commit()


async def run_sweep(
    session_maker: async_sessionmaker[AsyncSession], bot: Bot, interval_seconds: int = SWEEP_INTERVAL_SECONDS
) -> None:
    """Expire unanswered captchas and keep wave alerts current, for as long as the bot runs."""
    forgotten_at: datetime.datetime | None = None
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with session_maker() as session:
                await expire_stale(bot, session)
                await waves.refresh_alerts(bot, session, utc_now())
                if forgotten_at is None or utc_now() - forgotten_at > _RETENTION_EVERY:
                    await forget_old(session)
                    forgotten_at = utc_now()
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
