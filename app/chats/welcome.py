"""The greeting a chat gives new members: one message per burst of joiners.

A message per person turned a dozen joins into a dozen greetings, which is
the wall of noise `remove_membership_notice` exists to clear. Whoever joins
while the last greeting is still up is added to it by an edit instead — an
edit notifies nobody, so only the first name in a burst is pinged.

The greeting stays `Chat.time_delete` seconds after the last joiner and is
then deleted; a chat that keeps its greetings (`time_delete` 0) starts a new
one after `BURST_SECONDS` without joins. What is up lives in this process
only: after a restart the next joiner simply gets a new greeting.
"""

import asyncio
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, User

from app.core import intro
from app.core.logging import get_logger
from app.db.models import Chat

logger = get_logger("chats.welcome")

KONNEKT_LINE = (
    "📱 <b>Konnekt</b> — всё для студентов в Чехии: чаты вузов, репетиторы, страховка и помощь с жизнью здесь."
)
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
    timer: asyncio.Task[None] | None = None


_up: dict[int, _Greeting] = {}
_locks: dict[int, asyncio.Lock] = {}


def text(names: list[str], others: int, chat_text: str | None) -> str:
    who = ", ".join(names) + (f" и ещё {others}" if others else "")
    lines = [f"👋 {who}, <b>добро пожаловать!</b>", KONNEKT_LINE]
    if chat_text:
        lines.append(chat_text)
    return "\n\n".join(lines)


async def greet(bot: Bot, chat: Chat, user: User) -> None:
    """Greet `user` in `chat`: in the greeting that is up, or in a new one."""
    name = user.mention_html(user.first_name)
    async with _locks.setdefault(chat.id, asyncio.Lock()):
        greeting = _up.get(chat.id)
        if greeting is not None:
            if await _add(bot, chat.id, greeting, name):
                _keep(bot, chat, greeting)
                return
            _drop(chat.id)
        greeting = await _post(bot, chat, name)
        if greeting is not None:
            _up[chat.id] = greeting
            _keep(bot, chat, greeting)


async def _post(bot: Bot, chat: Chat, name: str) -> _Greeting | None:
    markup = await _markup(bot)
    try:
        sent, video = await intro.send(bot, chat.id, text([name], 0, chat.welcome_message), markup)
    except TelegramAPIError as err:
        # A greeting Telegram refuses is the chat's problem, not the join's.
        logger.warning("welcome_not_sent", chat_id=chat.id, error=str(err), error_type=type(err).__name__)
        return None
    return _Greeting(
        message_id=sent.message_id, video=video, markup=markup, chat_text=chat.welcome_message, names=[name]
    )


async def _add(bot: Bot, chat_id: int, greeting: _Greeting, name: str) -> bool:
    """Add a name to the greeting that is up; False when it cannot be edited any more."""
    names, others = greeting.names, greeting.others
    if len(names) < NAMED:
        names = [*names, name]
    else:
        others += 1
    body = text(names, others, greeting.chat_text)
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
    greeting.names, greeting.others = names, others
    return True


async def _markup(bot: Bot) -> InlineKeyboardMarkup:
    # A Mini App button is refused in a group; the bot's startapp link opens
    # the same app and tells it where the visitor came from.
    me = await bot.me()
    url = f"https://t.me/{me.username}?startapp={SOURCE}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=intro.OPEN_BUTTON, url=url)]])


def _keep(bot: Bot, chat: Chat, greeting: _Greeting) -> None:
    """(Re)start the greeting's clock from now, the latest join."""
    if greeting.timer is not None:
        greeting.timer.cancel()
    greeting.timer = asyncio.create_task(_run_out(bot, chat.id, greeting, chat.time_delete))


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
    """Forget every greeting that is up, as a restart would."""
    for greeting in _up.values():
        if greeting.timer is not None:
            greeting.timer.cancel()
    _up.clear()
    _locks.clear()
