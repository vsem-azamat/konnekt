"""The captcha asked in the chat: let in muted, named there, asked in a private message.

The private message a join request allows is open five minutes, and most
applicants never read it: of 49 delivered on 28-29.10, 37 went unanswered
without a single tap. With `Chat.captcha_in_chat` the bot mutes the applicant
and only then approves the request, so there is no moment they could write,
and names them in the chat, which notifies a member. The card's button opens
the bot; after /start it may write to them at any time, so the question and
its reminder go there. Passed, they may write and the chat greets them; out
of time or out of tries, they are removed together with anything they posted.

At most one card goes up per `card_batch_seconds`, naming everyone let in
since the last: a burst is one message. Who still waits from an earlier card
is carried into the new one by name without a link, which notifies nobody a
second time, and the earlier card is deleted. A card is edited when somebody
in it stops waiting (an edit notifies nobody) and deleted when nobody is left.

The service decides; this module does the chat's half in Telegram.
"""

import datetime
import html
import math
from collections.abc import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import challenge
from app.captcha.locks import lock_chat
from app.captcha.metrics import CAPTCHA_EVENTS
from app.captcha.telegram import with_retry
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Chat, JoinCaptcha

logger = get_logger("captcha.in_chat")

# Every permission there is, so one Telegram adds is not left open by omission.
# Nothing they could post, react with or change.
MUTED = ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, False))
# An exception that allows everything is no exception: the chat's own defaults apply again.
UNMUTED = ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, True))
# Named so when Telegram will not say who it is.
_UNNAMED = "новичок"


async def mute(bot: Bot, row: JoinCaptcha) -> None:
    """Restrict the applicant; raises what Telegram said. Works before they are a member, which is the point."""
    await with_retry(
        lambda: bot.restrict_chat_member(
            chat_id=row.chat_id, user_id=row.user_id, permissions=MUTED, use_independent_chat_permissions=True
        )
    )


async def unmute(bot: Bot, row: JoinCaptcha) -> bool:
    try:
        await with_retry(
            lambda: bot.restrict_chat_member(
                chat_id=row.chat_id, user_id=row.user_id, permissions=UNMUTED, use_independent_chat_permissions=True
            )
        )
    except TelegramAPIError as err:
        logger.warning("captcha_not_unmuted", captcha_id=row.id, error=str(err), error_type=type(err).__name__)
        return False
    return True


async def remove(bot: Bot, row: JoinCaptcha) -> bool:
    """Out of the chat with whatever they posted, and free to join again."""
    try:
        await with_retry(lambda: bot.ban_chat_member(chat_id=row.chat_id, user_id=row.user_id, revoke_messages=True))
        await with_retry(lambda: bot.unban_chat_member(chat_id=row.chat_id, user_id=row.user_id, only_if_banned=True))
    except TelegramAPIError as err:
        logger.warning("captcha_not_removed", captcha_id=row.id, error=str(err), error_type=type(err).__name__)
        return False
    return True


async def member(bot: Bot, row: JoinCaptcha) -> User | None:
    try:
        return (await bot.get_chat_member(chat_id=row.chat_id, user_id=row.user_id)).user
    except TelegramAPIError as err:
        logger.warning("captcha_member_unknown", captcha_id=row.id, error=str(err), error_type=type(err).__name__)
        return None


async def announce(bot: Bot, db: AsyncSession, chat_id: int, now: datetime.datetime) -> None:
    """Put up a card naming whoever was let in since the last one, unless the last went up too recently.

    The sweep calls this too, for the newcomers a recent card made wait.
    """
    await lock_chat(db, chat_id)
    waiting = (await db.scalars(_waiting(chat_id).order_by(JoinCaptcha.created_at))).all()
    new = [row for row in waiting if row.announced_at is None]
    if not new:
        await db.rollback()
        return
    last = await db.scalar(
        select(func.max(JoinCaptcha.announced_at)).where(JoinCaptcha.chat_id == chat_id, JoinCaptcha.in_chat)
    )
    if last is not None and now - last < datetime.timedelta(seconds=settings.captcha.card_batch_seconds):
        await db.rollback()
        return

    carried = [row for row in waiting if row.announced_at is not None]
    earlier = {row.card_message_id for row in carried if row.card_message_id is not None}
    names = await _first_names(bot, chat_id, waiting)
    body = challenge.card_text(
        [html.escape(names[row.user_id]) for row in carried]
        + [_mention(row.user_id, names[row.user_id]) for row in new],
        settings.captcha.answer_minutes,
    )
    markup = await _markup(bot)
    # Tried for this window whatever comes of it: a chat the bot cannot post
    # in would otherwise be asked again at every sweep.
    for row in new:
        row.announced_at = now
    try:
        sent = await with_retry(lambda: bot.send_message(chat_id=chat_id, text=body, reply_markup=markup))
    except TelegramAPIError as err:
        await db.commit()
        logger.warning("captcha_card_not_sent", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return
    for row in waiting:
        row.card_message_id = sent.message_id
    await db.commit()
    CAPTCHA_EVENTS.labels(event="card").inc()
    logger.info("captcha_card_sent", chat_id=chat_id, named=len(new), carried=len(carried))
    for message_id in earlier:
        await _delete(bot, chat_id, message_id)


async def announce_due(bot: Bot, db: AsyncSession, now: datetime.datetime) -> None:
    """Cards for every chat with newcomers nobody has named yet."""
    chats = (
        await db.scalars(
            select(JoinCaptcha.chat_id)
            .where(
                JoinCaptcha.in_chat,
                JoinCaptcha.status == JoinCaptcha.STATUS_PENDING,
                JoinCaptcha.announced_at.is_(None),
            )
            .distinct()
        )
    ).all()
    await db.rollback()
    for chat_id in chats:
        await announce(bot, db, chat_id, now)


async def refresh(bot: Bot, db: AsyncSession, chat_id: int, card_message_id: int | None) -> None:
    """The card again after somebody in it stopped waiting: without them, or gone when nobody is left."""
    if card_message_id is None:
        return
    rows = (
        await db.scalars(
            select(JoinCaptcha).where(JoinCaptcha.chat_id == chat_id, JoinCaptcha.card_message_id == card_message_id)
        )
    ).all()
    waiting = [row for row in rows if row.status == JoinCaptcha.STATUS_PENDING]
    if not waiting:
        await _delete(bot, chat_id, card_message_id)
        return
    # Those the card named with a link keep it; an edit notifies nobody either way.
    newest = max(row.announced_at for row in rows if row.announced_at is not None)
    names = await _first_names(bot, chat_id, waiting)
    body = challenge.card_text(
        [
            _mention(row.user_id, names[row.user_id]) if row.announced_at == newest else html.escape(names[row.user_id])
            for row in waiting
        ],
        settings.captcha.answer_minutes,
    )
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=card_message_id, text=body, reply_markup=await _markup(bot)
        )
    except TelegramAPIError as err:
        logger.info("captcha_card_not_edited", chat_id=chat_id, error=str(err), error_type=type(err).__name__)


async def ask(bot: Bot, db: AsyncSession, user_id: int, now: datetime.datetime) -> int:
    """The question in a private message, one per chat this person waits in; returns how many went out.

    Asked again on every tap of the card's button: a second message is easier
    to find than the first, and both answer the same captcha.
    """
    rows = (
        await db.scalars(
            select(JoinCaptcha)
            .where(
                JoinCaptcha.user_id == user_id,
                JoinCaptcha.in_chat,
                JoinCaptcha.status == JoinCaptcha.STATUS_PENDING,
                JoinCaptcha.expires_at > now,
            )
            .order_by(JoinCaptcha.created_at)
            .with_for_update()
        )
    ).all()
    asked = 0
    for row in rows:
        chat = await db.get(Chat, row.chat_id)
        title = (chat.title if chat else None) or str(row.chat_id)
        minutes_left = math.ceil((row.expires_at - now) / datetime.timedelta(minutes=1))
        try:
            sent = await with_retry(
                lambda row=row, title=title, minutes_left=minutes_left: bot.send_message(
                    chat_id=user_id,
                    text=challenge.ask_in_chat_text(title, row.answer, minutes_left),
                    reply_markup=challenge.keyboard(row.id, row.options),
                )
            )
        except TelegramAPIError as err:
            logger.warning("captcha_not_asked", captcha_id=row.id, error=str(err), error_type=type(err).__name__)
            continue
        row.message_id = sent.message_id
        row.user_chat_id = user_id
        row.asked_at = now
        asked += 1
        CAPTCHA_EVENTS.labels(event="sent").inc()
    await db.commit()
    return asked


def _waiting(chat_id: int):  # noqa: ANN202 - a Select of JoinCaptcha
    return select(JoinCaptcha).where(
        JoinCaptcha.chat_id == chat_id, JoinCaptcha.in_chat, JoinCaptcha.status == JoinCaptcha.STATUS_PENDING
    )


async def _first_names(bot: Bot, chat_id: int, rows: Sequence[JoinCaptcha]) -> dict[int, str]:
    """Asked of Telegram each time rather than kept: a name is the one thing here nobody needs stored."""
    names = {}
    for row in rows:
        try:
            user = (await bot.get_chat_member(chat_id=chat_id, user_id=row.user_id)).user
        except TelegramAPIError:
            names[row.user_id] = _UNNAMED
        else:
            names[row.user_id] = user.first_name or _UNNAMED
    return names


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


async def _markup(bot: Bot) -> InlineKeyboardMarkup:
    me = await bot.me()
    url = f"https://t.me/{me.username}?start={challenge.START_PAYLOAD}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=challenge.CARD_BUTTON, url=url)]])


async def _delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as err:
        logger.info("captcha_card_not_deleted", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
