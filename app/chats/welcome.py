"""The greeting a chat gives new members: one message per burst of joiners.

A message per person turned a dozen joins into a dozen greetings, which is
the wall of noise `remove_membership_notice` exists to clear. Whoever joins
while the last greeting is still up is added to it by an edit instead — an
edit notifies nobody, so only the first name in a burst is pinged.

The greeting stays `Chat.time_delete` seconds after the last joiner and is
then deleted; a chat that keeps its greetings (`time_delete` 0) starts a new
one after `BURST_SECONDS` without joins. What is up lives in this process
only: after a restart the next joiner gets a new greeting, and one that was
up when the bot stopped is not deleted.
"""

import asyncio
import html
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, User

from app.core import intro
from app.core.logging import get_logger

logger = get_logger("chats.welcome")

# Names shown before the rest are counted: «Marek, Tereza, Jakub и ещё 2».
NAMED = 3
BURST_SECONDS = 300
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


async def greet(bot: Bot, chat_id: int, user: User, *, chat_text: str | None, lifetime: int) -> None:
    """Greet `user`: in the greeting that is up, or in a new one.

    Takes the chat's settings as values, not its row: joiners queue on the
    lock while Telegram answers, and none of them should hold a database
    connection meanwhile.
    """
    async with _locks.setdefault(chat_id, asyncio.Lock()):
        greeting = _up.get(chat_id)
        if greeting is not None:
            if user.id in greeting.user_ids:
                return
            if await _add(bot, chat_id, greeting, user):
                _keep(bot, chat_id, greeting, lifetime)
                return
            _drop(chat_id)
        greeting = await _post(bot, chat_id, user, chat_text)
        if greeting is not None:
            _up[chat_id] = greeting
            _keep(bot, chat_id, greeting, lifetime)


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


def _keep(bot: Bot, chat_id: int, greeting: _Greeting, lifetime: int) -> None:
    """(Re)start the greeting's clock from now, the latest join."""
    if greeting.timer is not None:
        greeting.timer.cancel()
    greeting.timer = asyncio.create_task(_run_out(bot, chat_id, greeting, lifetime))
    _timers.add(greeting.timer)
    greeting.timer.add_done_callback(_timers.discard)


async def _run_out(bot: Bot, chat_id: int, greeting: _Greeting, lifetime: int) -> None:
    await _sleep(lifetime or BURST_SECONDS)
    async with _locks[chat_id]:
        if _up.get(chat_id) is greeting:
            del _up[chat_id]
    if not lifetime:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=greeting.message_id)
    except TelegramAPIError as err:
        logger.debug("welcome_not_deleted", chat_id=chat_id, error=str(err), error_type=type(err).__name__)


def _drop(chat_id: int) -> None:
    # Its clock keeps running: whatever is left of it is still deleted on time.
    _up.pop(chat_id, None)


def forget() -> None:
    """Forget every greeting and its clock, as a restart does."""
    for timer in _timers:
        timer.cancel()
    _timers.clear()
    _up.clear()
    _locks.clear()
