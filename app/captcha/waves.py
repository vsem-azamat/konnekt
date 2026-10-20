"""Waves: when join requests come faster than people do, stop writing to them.

Farmed accounts arrive by the hundred within minutes. Answering each with a
private message would spend the bot's rate limit on them and do nothing a
paused captcha does not: during a wave nobody is written to and nobody gets
in, the requests wait in Telegram, and the report chat gets one message whose
buttons decide what happens to them.

The pause holds until a quiet spell has passed since the last burst, so a wave
that stops for a minute and starts again is still the same wave. A wave an
admin resumed is not extended: if the burst goes on after that, it is a new
wave with a new alert, or a single press would switch the safeguard off for
the rest of the raid.
"""

import contextlib
import datetime
import html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha.telegram import request_gone, with_retry
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinCaptcha, JoinWave

logger = get_logger("captcha.waves")

# People asking to join one chat within a minute that make a wave. The busiest
# chats see a handful a day; twenty a minute is not a semester starting.
PER_MINUTE = 20
QUIET_MINUTES = 15
# Declined per transaction, so a restart loses at most this much progress.
_BATCH = 50

DECLINE = JoinWave.DECISION_DECLINE
RESUME = JoinWave.DECISION_RESUME
LEAVE = JoinWave.DECISION_LEAVE


class WaveDecision(CallbackData, prefix="wave"):
    wave_id: int
    action: str


def pauses(wave: JoinWave | None) -> bool:
    """Whether a request in this wave is held rather than sent the captcha."""
    return wave is not None and wave.decision != RESUME


async def surge(db: AsyncSession, chat: Chat, user_id: int, now: datetime.datetime) -> tuple[JoinWave | None, bool]:
    """The wave a request arriving now belongs to, and whether this request opened it.

    Call under the chat's lock and before the request is stored: it counts as
    one of the minute. Nothing is committed and nothing sent; an opened wave
    is the caller's to announce once it is committed.
    """
    current = await db.scalar(
        select(JoinWave)
        .where(
            JoinWave.chat_id == chat.id,
            JoinWave.last_surge_at > now - datetime.timedelta(minutes=QUIET_MINUTES),
        )
        .order_by(JoinWave.id.desc())
        .limit(1)
    )
    since = now - datetime.timedelta(minutes=1)
    if current is not None and current.decision == RESUME and current.decided_at is not None:
        # The burst the admin let through does not count against the next one.
        since = max(since, current.decided_at)

    # People, not requests: one person asking twice is not two bots.
    seen = set(
        await db.scalars(
            select(JoinCaptcha.user_id).where(JoinCaptcha.chat_id == chat.id, JoinCaptcha.created_at > since)
        )
    )
    seen.add(user_id)
    if len(seen) <= PER_MINUTE:
        return current, False

    if pauses(current):
        assert current is not None
        current.last_surge_at = now
        return current, False

    wave = JoinWave(chat_id=chat.id, started_at=now)
    db.add(wave)
    await db.flush()
    logger.warning("join_wave_started", chat_id=chat.id, wave_id=wave.id)
    return wave, True


async def announce(bot: Bot, db: AsyncSession, wave: JoinWave, chat: Chat) -> None:
    try:
        sent = await bot.send_message(
            chat_id=settings.admin.default_report_chat_id,
            text=_alert_text(chat, held=await _held_count(db, wave)),
            reply_markup=_buttons(wave.id),
        )
    except TelegramAPIError as err:
        # The pause works without the alert; only the buttons are lost.
        logger.error("join_wave_alert_not_sent", chat_id=chat.id, wave_id=wave.id, error=str(err))
        return
    wave.alert_message_id = sent.message_id
    await db.commit()


def _alert_text(chat: Chat, *, held: int) -> str:
    return (
        f"<b>Набег на {html.escape(chat.title or str(chat.id))}</b>\n\n"
        f"Больше {PER_MINUTE} заявок в минуту. Капча на паузе: новым людям бот не пишет, "
        f"в чат никто не вошёл.\n\n"
        f"Ждут решения: {held}."
    )


def _buttons(wave_id: int) -> InlineKeyboardMarkup:
    def button(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=WaveDecision(wave_id=wave_id, action=action).pack())

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Отклонить все", DECLINE)],
            [button("Снять паузу", RESUME), button("Пусть висят", LEAVE)],
        ]
    )


async def decision_of(db: AsyncSession, wave_id: int) -> str | None:
    return await db.scalar(select(JoinWave.decision).where(JoinWave.id == wave_id))


async def decide(
    bot: Bot,
    db: AsyncSession,
    *,
    wave_id: int,
    action: str,
    admin_id: int,
    admin_name: str,
    now: datetime.datetime | None = None,
) -> str | None:
    """Settle a wave; returns what was done, or None if it was settled another way.

    Pressing the same button again picks up where the first press stopped, so
    a restart halfway through declining a wave loses nothing but time.
    """
    now = now or utc_now()
    wave = await db.scalar(select(JoinWave).where(JoinWave.id == wave_id).with_for_update())
    if wave is None or action not in (DECLINE, RESUME, LEAVE):
        return None
    if wave.decision is not None and wave.decision != action:
        return None
    if wave.decision is None:
        wave.decision = action
        wave.decided_by = admin_id
        wave.decided_at = now
    await db.commit()

    chat = await db.get(Chat, wave.chat_id)
    title = html.escape(chat.title if chat and chat.title else str(wave.chat_id))
    who = f"{html.escape(admin_name)}, {now:%H:%M} UTC"

    if action == DECLINE and not (chat and chat.resource_status == Chat.STATUS_APPROVED and chat.is_captcha_enabled):
        # Like every other decision on a request: only in a chat that still asks for it.
        note = (
            f"<b>Набег на {title}</b> ({who}).\n\nЧат больше не модерируется или капча в нём выключена: "
            f"бот никого не отклонил, заявки ждут админов чата."
        )
    elif action == DECLINE:
        declined, failed = await _decline_held(bot, db, wave, now)
        note = (
            f"<b>Набег на {title}: отбит</b>\n\nОтклонено {declined} заявок ({who}). "
            f"Новые заявки этой волны тоже отклоняются. Через {QUIET_MINUTES} минут после того, "
            f"как набег стих, капча снова работает как обычно."
        )
        if failed:
            note += f"\n\nНе удалось отклонить {failed}: нажмите кнопку ещё раз или решите их в Telegram."
    elif action == RESUME:
        held = await _held_count(db, wave)
        note = (
            f"<b>Набег на {title}: пауза снята</b> ({who}).\n\nНовые заявки снова получают капчу; "
            f"если набег продолжится, придёт новое сообщение. {held} заявок из волны висят: "
            f"написать им бот уже не может, решают админы чата."
        )
    else:
        held = await _held_count(db, wave)
        note = (
            f"<b>Набег на {title}: заявки висят</b> ({who}).\n\n{held} заявок ждут админов чата. "
            f"Капча вернётся через {QUIET_MINUTES} минут тишины."
        )

    logger.info("join_wave_decided", wave_id=wave.id, chat_id=wave.chat_id, action=action, admin_id=admin_id)
    if wave.alert_message_id is not None:
        # Declining keeps its button: a press after a restart, or after a refusal, finishes the job.
        markup = _decline_again(wave.id) if action == DECLINE else None
        try:
            await bot.edit_message_text(
                chat_id=settings.admin.default_report_chat_id,
                message_id=wave.alert_message_id,
                text=note,
                reply_markup=markup,
            )
        except TelegramAPIError as err:
            logger.warning("join_wave_alert_not_edited", wave_id=wave.id, error=str(err))
    return note


def _decline_again(wave_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отклонить оставшиеся",
                    callback_data=WaveDecision(wave_id=wave_id, action=DECLINE).pack(),
                )
            ]
        ]
    )


async def _held_count(db: AsyncSession, wave: JoinWave) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(JoinCaptcha)
        .where(JoinCaptcha.wave_id == wave.id, JoinCaptcha.status == JoinCaptcha.STATUS_HELD)
    )
    return count or 0


async def _decline_held(bot: Bot, db: AsyncSession, wave: JoinWave, now: datetime.datetime) -> tuple[int, int]:
    """Decline the wave's held requests in batches, including any held meanwhile; (declined, failed)."""
    declined = 0
    failed: set[int] = set()
    while True:
        query = select(JoinCaptcha).where(JoinCaptcha.wave_id == wave.id, JoinCaptcha.status == JoinCaptcha.STATUS_HELD)
        if failed:
            query = query.where(JoinCaptcha.id.not_in(failed))
        # Skipped if locked: two presses at once share the work instead of doubling it.
        batch = (await db.scalars(query.order_by(JoinCaptcha.id).limit(_BATCH).with_for_update(skip_locked=True))).all()
        if not batch:
            break
        for row in batch:
            # One at a time and waiting out flood control: there is no batch call,
            # and a wave is exactly when Telegram starts saying "slow down".
            try:
                await with_retry(
                    lambda row=row: bot.decline_chat_join_request(chat_id=row.chat_id, user_id=row.user_id)
                )
            except TelegramAPIError as err:
                if not request_gone(err):
                    failed.add(row.id)
                    logger.warning("join_wave_decline_failed", captcha_id=row.id, error=str(err))
                    continue
                row.status = JoinCaptcha.STATUS_GONE
            else:
                row.status = JoinCaptcha.STATUS_DECLINED
                declined += 1
            row.resolved_at = now
        await db.commit()
    return declined, len(failed)


async def refresh_alerts(bot: Bot, db: AsyncSession, now: datetime.datetime) -> None:
    """Keep the count on undecided alerts current, while their wave is still running."""
    open_waves = (
        await db.scalars(
            select(JoinWave).where(
                JoinWave.decision.is_(None),
                JoinWave.alert_message_id.is_not(None),
                JoinWave.last_surge_at > now - datetime.timedelta(minutes=QUIET_MINUTES + 1),
            )
        )
    ).all()
    for wave in open_waves:
        chat = await db.get(Chat, wave.chat_id)
        if chat is None or wave.alert_message_id is None:
            continue
        # "Message is not modified" when nothing new arrived, which is most sweeps.
        with contextlib.suppress(TelegramAPIError):
            await bot.edit_message_text(
                chat_id=settings.admin.default_report_chat_id,
                message_id=wave.alert_message_id,
                text=_alert_text(chat, held=await _held_count(db, wave)),
                reply_markup=_buttons(wave.id),
            )
