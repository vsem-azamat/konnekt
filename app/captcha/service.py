"""The join captcha: one private message per applicant, answered by a tap.

Telegram lets a bot write to someone who asked to join for five minutes, so the
captcha goes out the moment the request arrives. The answer window, in
`settings.captcha`, may run longer: a request can be settled at any time. The
right emoji approves the request; two wrong ones, or silence, decline it. A
declined applicant is not banned and may ask again.

Somebody who passed the captcha in another of our chats within
`settings.captcha.trust_days` is approved without one, waves or not: the
captcha proves there is a person behind the account, and they already have.

Somebody who tapped to join one of our chats in the Mini App's catalog is
approved without one too, once: Telegram signed that tap (`CatalogPass`).

Every decision locks its row, so a tap and the expiry sweep cannot both act on
one request: whichever comes second finds it settled.
"""

import asyncio
import datetime
import enum
import html
import math

from aiogram import Bot
from aiogram.exceptions import AiogramError, TelegramAPIError
from aiogram.types import ChatJoinRequest, InlineKeyboardMarkup, ReplyParameters
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.captcha import challenge, waves
from app.captcha.metrics import CAPTCHA_EVENTS
from app.captcha.telegram import already_member, lacks_rights, report, request_gone, with_retry
from app.chats import welcome
from app.core import intro
from app.core.config import settings
from app.core.enums import ModerationEventAction
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import CatalogPass, Chat, JoinCaptcha, JoinWave, ModerationEvent

logger = get_logger("captcha")

SWEEP_INTERVAL_SECONDS = 15
# As long as what people wrote is kept (#174), and swept as rarely.
RETENTION_DAYS = 180
_RETENTION_EVERY = datetime.timedelta(hours=6)
_UNDELIVERED_EVERY = datetime.timedelta(minutes=10)
# How long after a request Telegram lets the bot write to its applicant.
_WRITE_WINDOW = datetime.timedelta(minutes=5)


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
    """Send the captcha for a request, unless trust lets them in or a wave says to hold or decline it.

    The blacklist is the caller's to check first: nothing here trusts past it.
    """
    now = now or utc_now()
    user_id = event.from_user.id

    # One request at a time per chat from the count to the insert: without it a
    # burst counts itself short and opens a wave per handful of requests.
    await _lock_chat(db, chat.id)
    superseded = await _supersede(db, chat.id, user_id, now)
    # A trusted request counts towards a wave like any other, so a raid of
    # accounts that once passed somewhere still raises the alert; it just
    # does not wait in one.
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
        expires_at=now + datetime.timedelta(minutes=settings.captcha.answer_minutes),
    )
    # Asked in this order so that a pass the person did not need is not spent.
    if await _trusted(db, chat.id, user_id, now):
        # Settled from the start, so the sweep never declines it. Should the
        # process stop before Telegram is asked, the row says trusted while
        # the request waits for the admins, as an undelivered one does.
        row.status = JoinCaptcha.STATUS_TRUSTED
        row.resolved_at = now
    elif waves.pauses(wave):
        assert wave is not None
        row.wave_id = wave.id
        row.status = JoinCaptcha.STATUS_HELD
    elif await _spend_catalog_pass(db, chat.id, user_id, now):
        # Not during a wave: a pass is cheap to mint, so it must not carry a
        # raid past a hold or an admin's decline. A held request keeps its
        # pass. The pass is deleted in the commit that records the row: one tap
        # opens the door once.
        row.status = JoinCaptcha.STATUS_CATALOG
        row.resolved_at = now
    db.add(row)
    await db.commit()

    for old in superseded:
        await _edit(bot, old, challenge.superseded_text(_title(chat)), None)
    if opened:
        assert wave is not None
        await waves.announce(bot, db, wave, chat)

    if row.status in (JoinCaptcha.STATUS_TRUSTED, JoinCaptcha.STATUS_CATALOG):
        await _let_in_on_trust(bot, db, row, chat)
        return

    if row.status == JoinCaptcha.STATUS_HELD:
        assert wave is not None
        CAPTCHA_EVENTS.labels(event=JoinCaptcha.STATUS_HELD).inc()
        if wave.decision == JoinWave.DECISION_DECLINE:
            await _decline_on_sight(bot, db, row, now)
        return

    try:
        sent = await with_retry(
            lambda: bot.send_message(
                chat_id=event.user_chat_id,
                text=challenge.ask_text(_title(chat), answer, settings.captcha.answer_minutes),
                reply_markup=challenge.keyboard(row.id, options),
            )
        )
    except TelegramAPIError as err:
        # Usually another bot wrote first, which closes the window. The request
        # stays as it was, for the admins, exactly as without a captcha.
        row.status = JoinCaptcha.STATUS_UNDELIVERED
        row.resolved_at = now
        await db.commit()
        CAPTCHA_EVENTS.labels(event=JoinCaptcha.STATUS_UNDELIVERED).inc()
        # Reported by the sweep, summed up per chat: a second captcha bot in
        # the chat makes every request land here.
        logger.warning(
            "captcha_not_delivered", chat_id=chat.id, user_id=user_id, error=str(err), error_type=type(err).__name__
        )
        return
    row.message_id = sent.message_id
    await db.commit()
    CAPTCHA_EVENTS.labels(event="sent").inc()
    logger.info("captcha_sent", chat_id=chat.id, user_id=user_id, captcha_id=row.id)


async def _trusted(db: AsyncSession, chat_id: int, user_id: int, now: datetime.datetime) -> bool:
    """Whether this person passed the captcha in another chat within the window and was never banned by us.

    Another chat only: coming back to one they left is asking again. Any ban
    or blacklisting on record outweighs the pass, however long ago and even
    if lifted since: that costs the person one captcha, and trusting someone
    still banned somewhere would cost a chat a spammer. Bans made in
    Telegram's own admin screens leave no record here and are not seen.
    """
    since = now - datetime.timedelta(days=settings.captcha.trust_days)
    passed = await db.scalar(
        select(JoinCaptcha.id)
        .where(
            JoinCaptcha.user_id == user_id,
            JoinCaptcha.chat_id != chat_id,
            JoinCaptcha.status == JoinCaptcha.STATUS_PASSED,
            JoinCaptcha.resolved_at >= since,
        )
        .limit(1)
    )
    if passed is None:
        return False
    return not await _ever_banned(db, user_id)


async def _ever_banned(db: AsyncSession, user_id: int) -> bool:
    banned = await db.scalar(
        select(ModerationEvent.id)
        .where(
            ModerationEvent.target_user_id == user_id,
            ModerationEvent.action.in_((ModerationEventAction.BAN, ModerationEventAction.BLACKLIST)),
        )
        .limit(1)
    )
    return banned is not None


async def _spend_catalog_pass(db: AsyncSession, chat_id: int, user_id: int, now: datetime.datetime) -> bool:
    """Whether this person tapped to join this chat in the catalog lately; if so, the pass is spent.

    Spent in one statement, so two requests at once cannot both use it (the
    chat is locked anyway). Not committed here: it goes with the captcha row.
    Somebody banned anywhere gets no pass, as with `_trusted`; their pass stays
    until it expires.
    """
    if await _ever_banned(db, user_id):
        return False
    spent = await db.execute(
        delete(CatalogPass).where(
            CatalogPass.user_id == user_id, CatalogPass.chat_id == chat_id, CatalogPass.expires_at > now
        )
    )
    return spent.rowcount == 1  # ty: ignore[unresolved-attribute]


async def _let_in_on_trust(bot: Bot, db: AsyncSession, row: JoinCaptcha, chat: Chat) -> None:
    """Tell the applicant they are in, then approve the request.

    In that order: Telegram lets the bot write to an applicant only until the
    request is settled. Should the approval fail, the note is edited to say so.
    """
    title = _title(chat)
    try:
        sent = await with_retry(
            lambda: bot.send_message(
                chat_id=row.user_chat_id,
                text=challenge.passed_text(title, _link(chat)),
                disable_web_page_preview=True,
            )
        )
    except TelegramAPIError as err:
        # Another bot wrote first, most likely. They get in all the same.
        logger.warning("captcha_trusted_not_told", captcha_id=row.id, error=str(err), error_type=type(err).__name__)
    else:
        row.message_id = sent.message_id
        await db.commit()

    try:
        await with_retry(lambda: bot.approve_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
    except TelegramAPIError as err:
        if not already_member(err):
            assert row.resolved_at is not None
            if request_gone(err):
                await _close(bot, db, row, JoinCaptcha.STATUS_GONE, row.resolved_at, challenge.gone_text(title))
                logger.info("captcha_request_gone", captcha_id=row.id)
                return
            await _close(bot, db, row, JoinCaptcha.STATUS_GONE, row.resolved_at, challenge.handed_back_text(title))
            logger.warning(
                "captcha_request_refused",
                captcha_id=row.id,
                chat_id=row.chat_id,
                error=str(err),
                error_type=type(err).__name__,
            )
            advice = "Проверьте права бота в чате." if lacks_rights(err) else "Заявка ждёт админов чата."
            await report(
                bot,
                f"Капча не смогла принять заявку в {html.escape(title)} ({row.user_id}): "
                f"{html.escape(err.message)}. {advice}",
            )
            return
    CAPTCHA_EVENTS.labels(event=row.status).inc()
    logger.info("captcha_trusted", chat_id=row.chat_id, user_id=row.user_id, captcha_id=row.id, source=row.status)


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
            logger.warning(
                "captcha_wave_decline_failed", captcha_id=row.id, error=str(err), error_type=type(err).__name__
            )
            return
        row.status = JoinCaptcha.STATUS_GONE
    else:
        row.status = JoinCaptcha.STATUS_DECLINED
    row.resolved_at = now
    await db.commit()
    CAPTCHA_EVENTS.labels(event=row.status).inc()


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
        await _introduce(bot, row, now)
        try:
            await with_retry(lambda: bot.approve_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        except TelegramAPIError as err:
            if not already_member(err):
                return await _refused(bot, db, row, now, title, err, verb="принять")
        await _close(bot, db, row, JoinCaptcha.STATUS_PASSED, now, challenge.passed_text(title, _link(chat)))
        logger.info("captcha_passed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.PASSED

    row.attempts_left -= 1
    if row.attempts_left > 0:
        CAPTCHA_EVENTS.labels(event="retry").inc()
    if row.attempts_left <= 0:
        try:
            await with_retry(lambda: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id))
        except TelegramAPIError as err:
            return await _refused(bot, db, row, now, title, err, verb="отклонить")
        await _close(bot, db, row, JoinCaptcha.STATUS_FAILED, now, challenge.failed_text(title))
        logger.info("captcha_failed", chat_id=row.chat_id, user_id=row.user_id)
        return Outcome.FAILED

    # The same board: the message names the answer and is not rewritten, the
    # popup the caller shows says what to tap. Two guesses on one board of
    # eight are no better odds than on two.
    await db.commit()
    return Outcome.RETRY


async def admitted(
    bot: Bot, db: AsyncSession, chat_id: int, user_id: int, *, now: datetime.datetime | None = None
) -> None:
    """Close the captcha of somebody who is in the chat already: an admin let them in by hand.

    Their request is settled, so the captcha is the admins' decision now. Left
    open, it would remind them to answer from inside the chat, and a late tap
    would try to settle a request that is gone. A row somebody holds — a tap
    mid-approve, a reminder being sent — is waited for, then read again: one
    the tap settled is left as it settled it.
    """
    now = now or utc_now()
    rows = (
        await db.scalars(
            select(JoinCaptcha)
            .where(
                JoinCaptcha.chat_id == chat_id,
                JoinCaptcha.user_id == user_id,
                JoinCaptcha.status.in_((JoinCaptcha.STATUS_PENDING, JoinCaptcha.STATUS_HELD)),
            )
            # Not skip_locked: the join arrives once, and a row skipped
            # while a wrong tap or a reminder held it would stay open.
            .with_for_update()
        )
    ).all()
    if not rows:
        await db.rollback()
        return
    chat = await db.get(Chat, chat_id)
    title = _title(chat) if chat else str(chat_id)
    for row in rows:
        row.status = JoinCaptcha.STATUS_GONE
        row.resolved_at = now
    await db.commit()
    for row in rows:
        CAPTCHA_EVENTS.labels(event=JoinCaptcha.STATUS_GONE).inc()
        await _edit(bot, row, challenge.gone_text(title), None)
    logger.info("captcha_admitted_by_hand", chat_id=chat_id, user_id=user_id, count=len(rows))


async def _introduce(bot: Bot, row: JoinCaptcha, now: datetime.datetime) -> None:
    """Konnekt in the private chat, before the approval settles the request and closes it.

    Whether it arrives decides nothing: the applicant is let in either way.
    """
    if now - row.created_at >= _WRITE_WINDOW:
        return
    try:
        await intro.send(bot, row.user_chat_id, challenge.INTRO, intro.private_markup())
    except AiogramError as err:
        logger.warning("captcha_intro_not_sent", captcha_id=row.id, error=str(err), error_type=type(err).__name__)


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
    # Nothing the applicant can fix, and something the admins must know.
    await _close(bot, db, row, JoinCaptcha.STATUS_GONE, now, challenge.handed_back_text(title))
    logger.warning(
        "captcha_request_refused", captcha_id=row.id, chat_id=row.chat_id, error=str(err), error_type=type(err).__name__
    )
    advice = "Проверьте права бота в чате." if lacks_rights(err) else "Telegram не ответил, заявка ждёт админов чата."
    await report(
        bot,
        f"Капча не смогла {verb} заявку в {html.escape(title)} ({row.user_id}): {html.escape(err.message)}. {advice}",
    )
    return Outcome.GONE


async def expire_stale(bot: Bot, db: AsyncSession, *, now: datetime.datetime | None = None) -> int:
    """Decline every captcha whose time ran out; returns how many were settled.

    One row per transaction, each locked and skipped if a tap holds it: the
    tap decides that one, and a failure halfway leaves the rows before it
    settled rather than rolled back to be declined a second time.
    """
    now = now or utc_now()
    # A chat that stopped checking (captcha switched off, approval withdrawn)
    # settles its open captchas at once: a day's window is too long to leave
    # applicants answering a board nobody will act on.
    stopped = select(Chat.id).where(
        or_(Chat.resource_status != Chat.STATUS_APPROVED, Chat.join_mode != Chat.JOIN_CAPTCHA)
    )
    due = (
        await db.scalars(
            select(JoinCaptcha.id).where(
                JoinCaptcha.status == JoinCaptcha.STATUS_PENDING,
                or_(JoinCaptcha.expires_at <= now, JoinCaptcha.chat_id.in_(stopped)),
            )
        )
    ).all()
    settled = 0
    for captcha_id in due:
        row = await db.scalar(
            select(JoinCaptcha)
            .where(JoinCaptcha.id == captcha_id, JoinCaptcha.status == JoinCaptcha.STATUS_PENDING)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            await db.rollback()
            continue
        chat = await db.get(Chat, row.chat_id)
        title = _title(chat) if chat else str(row.chat_id)
        if not _still_checks(chat):
            status, note = JoinCaptcha.STATUS_GONE, challenge.handed_back_text(title)
        else:
            try:
                await with_retry(
                    lambda row=row: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id)
                )
            except TelegramAPIError as err:
                # Settled by an admin meanwhile, or not ours to settle any more:
                # either way the applicant must not be told "declined".
                if request_gone(err):
                    status, note = JoinCaptcha.STATUS_GONE, challenge.gone_text(title)
                else:
                    status, note = JoinCaptcha.STATUS_GONE, challenge.handed_back_text(title)
                    logger.warning(
                        "captcha_expiry_refused", captcha_id=row.id, error=str(err), error_type=type(err).__name__
                    )
            else:
                status, note = JoinCaptcha.STATUS_EXPIRED, challenge.expired_text(title)
        await _close(bot, db, row, status, now, note)
        settled += 1
    if settled:
        logger.info("captcha_expired", count=settled)
    return settled


async def remind(bot: Bot, db: AsyncSession, *, now: datetime.datetime | None = None) -> None:
    """Write once more to applicants who have not answered, while Telegram still allows it.

    The first message comes with the request and is easy to miss; editing it
    later notifies nobody, so the reminder is a new message, sent at most once.
    The row stays locked until it is sent, so a tap waits for the reminder
    rather than being followed by it.
    """
    now = now or utc_now()
    due = (
        JoinCaptcha.status == JoinCaptcha.STATUS_PENDING,
        JoinCaptcha.message_id.is_not(None),
        JoinCaptcha.reminded_at.is_(None),
        JoinCaptcha.created_at <= now - datetime.timedelta(minutes=settings.captcha.remind_after_minutes),
        JoinCaptcha.created_at > now - _WRITE_WINDOW,
        JoinCaptcha.expires_at > now,
    )
    for captcha_id in (await db.scalars(select(JoinCaptcha.id).where(*due))).all():
        row = await db.scalar(
            select(JoinCaptcha).where(JoinCaptcha.id == captcha_id, *due).with_for_update(skip_locked=True)
        )
        if row is None:
            await db.rollback()
            continue
        row.reminded_at = now
        chat = await db.get(Chat, row.chat_id)
        # Taken off captcha meanwhile: the request is the admins' and a tap would decide nothing.
        if not _still_checks(chat):
            await db.commit()
            continue
        assert chat is not None
        assert row.message_id is not None
        minutes_left = math.ceil((row.expires_at - now) / datetime.timedelta(minutes=1))
        try:
            await bot.send_message(
                chat_id=row.user_chat_id,
                text=challenge.reminder_text(row.answer, minutes_left),
                reply_parameters=ReplyParameters(message_id=row.message_id, allow_sending_without_reply=True),
            )
        except TelegramAPIError as err:
            await db.commit()
            logger.warning(
                "captcha_reminder_not_delivered", captcha_id=row.id, error=str(err), error_type=type(err).__name__
            )
            continue
        await db.commit()
        CAPTCHA_EVENTS.labels(event="reminded").inc()
        logger.info("captcha_reminded", captcha_id=row.id)


async def report_undelivered(bot: Bot, db: AsyncSession, *, since: datetime.datetime, until: datetime.datetime) -> None:
    """One summary of the captchas that could not be sent, instead of a line per applicant.

    A captcha that does not arrive is nearly always another bot in the chat
    writing first, and that happens to every request, not one in a hundred.
    """
    rows = (
        await db.execute(
            select(JoinCaptcha.chat_id, func.count())
            .where(
                JoinCaptcha.status == JoinCaptcha.STATUS_UNDELIVERED,
                JoinCaptcha.resolved_at > since,
                JoinCaptcha.resolved_at <= until,
            )
            .group_by(JoinCaptcha.chat_id)
        )
    ).all()
    if not rows:
        return
    lines = []
    for chat_id, count in rows:
        chat = await db.get(Chat, chat_id)
        lines.append(f"• {html.escape(_title(chat) if chat else str(chat_id))}: {count}")
    await report(
        bot,
        "Капча не дошла до заявителей, их заявки ждут админов чата:\n"
        + "\n".join(lines)
        + "\n\nОбычно так бывает, когда в чате есть другой бот с капчей: написать заявителю может только первый.",
    )


async def forget_old(db: AsyncSession, *, now: datetime.datetime | None = None) -> None:
    """Drop settled captchas and waves past the retention period."""
    cutoff = (now or utc_now()) - datetime.timedelta(days=RETENTION_DAYS)
    await db.execute(delete(JoinCaptcha).where(JoinCaptcha.created_at < cutoff, JoinCaptcha.resolved_at.is_not(None)))
    await db.execute(delete(JoinWave).where(JoinWave.last_surge_at < cutoff))
    await db.execute(delete(CatalogPass).where(CatalogPass.expires_at < (now or utc_now())))
    await db.commit()


async def run_sweep(
    session_maker: async_sessionmaker[AsyncSession], bot: Bot, interval_seconds: int = SWEEP_INTERVAL_SECONDS
) -> None:
    """Expire and remind unanswered captchas and keep wave alerts current, for as long as the bot runs.

    Chat greetings whose time is up are deleted here too: the one loop the bot
    already runs this often, and the one that outlives the process that posted them.
    """
    forgotten_at: datetime.datetime | None = None
    reported_at = utc_now()
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with session_maker() as session:
                await expire_stale(bot, session)
                await remind(bot, session)
                await welcome.sweep(bot, session)
                await waves.refresh_alerts(bot, session, utc_now())
                if utc_now() - reported_at > _UNDELIVERED_EVERY:
                    until = utc_now()
                    await report_undelivered(bot, session, since=reported_at, until=until)
                    reported_at = until
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
    CAPTCHA_EVENTS.labels(event=status).inc()
    await _edit(bot, row, text, markup)


async def _edit(bot: Bot, row: JoinCaptcha, text: str, markup: InlineKeyboardMarkup | None) -> None:
    if row.message_id is None:
        return
    try:
        # The chat's link in «Готово» needs no preview card under it.
        await bot.edit_message_text(
            chat_id=row.user_chat_id,
            message_id=row.message_id,
            text=text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramAPIError as err:
        # The decision stands either way; the applicant just sees stale buttons.
        logger.warning("captcha_message_not_edited", captcha_id=row.id, error=str(err), error_type=type(err).__name__)


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
