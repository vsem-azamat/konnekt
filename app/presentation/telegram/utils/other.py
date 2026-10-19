import asyncio
import contextlib
import datetime
import re
from zoneinfo import ZoneInfo

from aiogram import types

from app.core.config import settings
from app.core.text import escape_html


async def _delete_later(message: types.Message, seconds: int) -> None:
    """Delete a message after a delay (background task)."""
    await asyncio.sleep(seconds)
    with contextlib.suppress(Exception):
        await message.delete()


# The event loop keeps only weak references to tasks; one nobody holds can be
# collected before it runs, and the message then stays.
_pending_deletions: set[asyncio.Task[None]] = set()


def sleep_and_delete(message: types.Message, seconds: int = 60) -> None:
    """Schedule a message for deletion after a delay (non-blocking)."""
    task = asyncio.create_task(_delete_later(message, seconds))
    _pending_deletions.add(task)
    task.add_done_callback(_pending_deletions.discard)


def get_user_mention(user: types.User) -> str:
    """Return mention markup for a user."""
    return user.mention_html()


def get_chat_mention(tg_object: types.Message | types.Chat) -> str:
    """Return HTML link to a chat or its message."""
    chat_link = get_chat_link(tg_object)
    if isinstance(tg_object, types.Message):
        return f'<a href="{chat_link}">{escape_html(tg_object.chat.title or "")}</a>'
    return f'<a href="{chat_link}">{escape_html(tg_object.title or "")}</a>'


def get_message_mention(message: types.Message) -> str:
    chat_link = get_message_link(message)
    return f'<a href="{chat_link}">Cообщение</a>'


def _strip_chat_id_prefix(chat_id: int) -> str:
    """Strip the -100 prefix from supergroup/channel IDs for t.me/c/ links."""
    s = str(chat_id)
    if s.startswith("-100"):
        return s[4:]
    return s.lstrip("-")


def get_message_link(tg_object: types.Message) -> str:
    """Generate a direct link to a message."""
    chat = tg_object.chat

    if chat.username:  # Public chat or channel
        return f"https://t.me/{chat.username}/{tg_object.message_id}"

    if chat.type in ["group", "supergroup"]:  # Private group without username
        return f"https://t.me/c/{_strip_chat_id_prefix(chat.id)}/{tg_object.message_id}"

    # Private 1-on-1 chat
    return f"https://t.me/{chat.id}/{tg_object.message_id}"


def get_chat_link(tg_object: types.Message | types.Chat) -> str:
    """Return a direct link to a chat."""
    chat = tg_object.chat if isinstance(tg_object, types.Message) else tg_object

    if chat.username:
        return f"https://t.me/{chat.username}"
    return f"https://t.me/c/{_strip_chat_id_prefix(chat.id)}"


_MUTE_COMMAND = re.compile(r"[!/]mute(?:@\w+)?(?:\s+(?P<time>\d+)\s*(?P<unit>[mhdw])?)?", re.IGNORECASE)


# Telegram reads an until_date more than 366 days away as forever.
MAX_MUTE = datetime.timedelta(days=366)


class MuteDuration:
    def __init__(self, until_date: datetime.datetime, time: int, unit: str):
        self.until_date = until_date
        self.time = time
        self.unit = unit

    def formatted_until_date(self) -> str:
        return self.until_date.strftime("%Y-%m-%d %H:%M:%S")


def calculate_mute_duration(message: str) -> MuteDuration:
    """Parse a `!mute` command into how long the mute lasts.

    The whole text must match: a typo used to become five minutes, and a zero
    became an until_date Telegram reads as forever, as is anything past 366 days.
    """
    parsed = _MUTE_COMMAND.fullmatch(message.strip())
    if not parsed:
        raise ValueError(f"Invalid mute command format: {message!r}")

    time = int(parsed.group("time") or 5)
    if time < 1:
        raise ValueError(f"Mute duration must be at least 1: {message!r}")
    unit = (parsed.group("unit") or "m").lower()

    # Define time units and calculate the duration
    units = {
        "m": datetime.timedelta(minutes=time),
        "h": datetime.timedelta(hours=time),
        "d": datetime.timedelta(days=time),
        "w": datetime.timedelta(weeks=time),
    }
    timedelta = units[unit]
    if timedelta > MAX_MUTE:
        raise ValueError(f"Mute duration over 366 days would be permanent: {message!r}")
    local_tz = ZoneInfo(settings.timezone)
    until_date = datetime.datetime.now(datetime.UTC).astimezone(local_tz) + timedelta

    return MuteDuration(until_date, time, unit)
