"""The greeting a chat gives new members: one message per burst of joiners.

A message per person turned a dozen joins into a dozen greetings, which is
the wall of noise `remove_membership_notice` exists to clear. Whoever joins
while the last greeting is still up is added to it by an edit instead — an
edit notifies nobody, so only the first name in a burst is pinged.

The greeting stays `Chat.time_delete` seconds after the last joiner and is
then deleted; a chat that keeps its greetings (`time_delete` 0) starts a new
one after `BURST_SECONDS` without joins. Which greeting is up lives in this
process only, so after a restart the next joiner gets a new one. When each is
to go is a row (`WelcomeGreeting`), and `sweep` deletes it from there: a
restart, a deploy among them, cannot leave a greeting up for good.
"""

import asyncio
import datetime
import html
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNotFound,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, User
from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import intro
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import WelcomeGreeting

logger = get_logger("chats.welcome")

# Names shown before the rest are counted: «Marek, Tereza, Jakub и ещё 2».
NAMED = 3
BURST_SECONDS = 300
# Greetings deleted per sweep: a backlog after a long stop goes over a few runs.
SWEEP_BATCH = 50
# Telegram lets a bot delete its own message for this long after it was sent.
DELETABLE_FOR = datetime.timedelta(hours=48)
# Refusals that asking again will not change.
_FINAL = (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramMigrateToChat)
# The source the Mini App records for people who came from a greeting.
SOURCE = "welcome"

_sleep = asyncio.sleep


@dataclass
class _Greeting:
    message_id: int
    video: bool
    markup: InlineKeyboardMarkup
    chat_text: str | None
    names: list[str] = field(default_factory=list)
    others: int = 0
    # Who is in it already: joining, leaving and joining again is one name.
    user_ids: set[int] = field(default_factory=set)
    timer: asyncio.Task[None] | None = None


_up: dict[int, _Greeting] = {}
_locks: dict[int, asyncio.Lock] = {}
_timers: set[asyncio.Task[None]] = set()


def text(names: list[str], others: int, chat_text: str | None) -> str:
    who = ", ".join(names) + (f" и ещё {others}" if others else "")
    lines = [f"👋 {who}, <b>добро пожаловать!</b>", intro.ABOUT]
    if chat_text:
        lines.append(chat_text)
    return "\n\n".join(lines)


async def greet(bot: Bot, chat_id: int, user: User, *, chat_text: str | None, lifetime: int) -> int | None:
    """Greet `user`: in the greeting that is up, or in a new one.

    Returns the greeting's message id, for the caller to record when it is to
    go, or None when nothing was sent or `user` is in it already. Takes the
    chat's settings as values, not its row: joiners queue on the lock while
    Telegram answers, and none of them should hold a database connection
    meanwhile.
    """
    async with _locks.setdefault(chat_id, asyncio.Lock()):
        greeting = _up.get(chat_id)
        if greeting is not None:
            if user.id in greeting.user_ids:
                return None
            if await _add(bot, chat_id, greeting, user):
                _keep(chat_id, greeting, lifetime)
                return greeting.message_id
            _drop(chat_id)
        greeting = await _post(bot, chat_id, user, chat_text)
        if greeting is None:
            return None
        _up[chat_id] = greeting
        _keep(chat_id, greeting, lifetime)
        return greeting.message_id


async def remember(db: AsyncSession, chat_id: int, message_id: int, lifetime: int) -> None:
    """Record that the greeting goes `lifetime` seconds from now; a chat that keeps them records nothing."""
    if not lifetime:
        return
    db.add(WelcomeGreeting(chat_id, message_id, utc_now() + datetime.timedelta(seconds=lifetime)))
    await db.commit()


async def sweep(bot: Bot, db: AsyncSession, *, now: datetime.datetime | None = None) -> None:
    """Delete every greeting whose last join's time is up, whether or not this process posted it.

    Oldest first, so greetings Telegram keeps refusing cannot take every run.
    A refusal that will not change is forgotten: the greeting is gone, the bot
    is out of the chat, or the group became a supergroup under another id.
    Flood control and the network are tried again on the next run, and past
    the 48 hours a bot may delete its own message in, nothing is tried at all.
    """
    now = now or utc_now()
    due = (await db.execute(_due(now).order_by(_last_join).limit(SWEEP_BATCH))).all()
    for chat_id, message_id, delete_at in due:
        if now - delete_at < DELETABLE_FOR:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except _FINAL as err:
                logger.info(
                    "welcome_not_deletable",
                    chat_id=chat_id,
                    message_id=message_id,
                    error=str(err),
                    error_type=type(err).__name__,
                )
            except TelegramAPIError as err:
                logger.warning(
                    "welcome_not_deleted",
                    chat_id=chat_id,
                    message_id=message_id,
                    error=str(err),
                    error_type=type(err).__name__,
                )
                continue
        await db.execute(
            delete(WelcomeGreeting).where(WelcomeGreeting.chat_id == chat_id, WelcomeGreeting.message_id == message_id)
        )
        await db.commit()


async def overdue(db: AsyncSession, *, now: datetime.datetime | None = None) -> int:
    """Greetings `sweep` should have deleted by now; above zero for long, it is not getting through."""
    due = _due(now or utc_now()).subquery()
    return await db.scalar(select(func.count()).select_from(due)) or 0


# A greeting is one message however many joiners extended it; the last join decides.
_last_join = func.max(WelcomeGreeting.delete_at)


def _due(now: datetime.datetime) -> Select[tuple[int, int, datetime.datetime]]:
    return (
        select(WelcomeGreeting.chat_id, WelcomeGreeting.message_id, _last_join)
        .group_by(WelcomeGreeting.chat_id, WelcomeGreeting.message_id)
        .having(_last_join <= now)
    )


def _name(user: User) -> str:
    return user.mention_html(user.first_name)


async def _post(bot: Bot, chat_id: int, user: User, chat_text: str | None) -> _Greeting | None:
    markup = await _markup(bot)
    try:
        try:
            sent, video = await intro.send(bot, chat_id, text([_name(user)], 0, chat_text), markup)
        except TelegramBadRequest as err:
            # `!welcome` stores HTML, the console stores what the admin typed:
            # a raw `<` there is not markup, and the greeting goes out as HTML.
            # Shown as typed rather than losing the whole greeting.
            if not chat_text or intro.PARSE_ERROR not in str(err):
                raise
            logger.warning("welcome_text_escaped", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
            chat_text = html.escape(chat_text, quote=False)
            sent, video = await intro.send(bot, chat_id, text([_name(user)], 0, chat_text), markup)
    except TelegramAPIError as err:
        # A greeting Telegram refuses is the chat's problem, not the join's.
        logger.warning("welcome_not_sent", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return None
    return _Greeting(
        message_id=sent.message_id,
        video=video,
        markup=markup,
        chat_text=chat_text,
        names=[_name(user)],
        user_ids={user.id},
    )


async def _add(bot: Bot, chat_id: int, greeting: _Greeting, user: User) -> bool:
    """Add a name to the greeting that is up; False when it is gone and a new one is needed."""
    names, others = [*greeting.names, _name(user)], greeting.others
    body = text(names, others, greeting.chat_text)
    # A name that would not fit under the video is counted instead.
    if len(names) > NAMED or (greeting.video and not intro.fits_caption(body)):
        names, others = greeting.names, others + 1
        body = text(names, others, greeting.chat_text)
    greeting.names, greeting.others = names, others
    greeting.user_ids.add(user.id)
    try:
        if greeting.video:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=greeting.message_id, caption=body, reply_markup=greeting.markup
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=greeting.message_id,
                text=body,
                reply_markup=greeting.markup,
                disable_web_page_preview=True,
            )
    except TelegramBadRequest as err:
        # Deleted by an admin, most likely. The newcomer gets a greeting of their own.
        logger.info("welcome_not_extended", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return False
    except TelegramAPIError as err:
        # Flood control, typically, which is what a burst of joins runs into.
        # The name is counted all the same and shows with the next edit.
        logger.warning("welcome_edit_skipped", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
    return True


async def _markup(bot: Bot) -> InlineKeyboardMarkup:
    # A Mini App button is refused in a group; the bot's startapp link opens
    # the same app and tells it where the visitor came from.
    me = await bot.me()
    url = f"https://t.me/{me.username}?startapp={SOURCE}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=intro.OPEN_BUTTON, url=url)]])


def _keep(chat_id: int, greeting: _Greeting, lifetime: int) -> None:
    """(Re)start the greeting's clock from now, the latest join: while it runs, joiners are added to it."""
    if greeting.timer is not None:
        greeting.timer.cancel()
    greeting.timer = asyncio.create_task(_run_out(chat_id, greeting, lifetime))
    _timers.add(greeting.timer)
    greeting.timer.add_done_callback(_timers.discard)


async def _run_out(chat_id: int, greeting: _Greeting, lifetime: int) -> None:
    # The next joiner gets a greeting of their own; deleting this one is `sweep`'s.
    await _sleep(lifetime or BURST_SECONDS)
    async with _locks[chat_id]:
        if _up.get(chat_id) is greeting:
            del _up[chat_id]


def _drop(chat_id: int) -> None:
    # Its rows stay: whatever is left of it is still deleted on time.
    _up.pop(chat_id, None)


def forget() -> None:
    """Forget every greeting and its clock, as a restart does."""
    for timer in _timers:
        timer.cancel()
    _timers.clear()
    _up.clear()
    _locks.clear()
