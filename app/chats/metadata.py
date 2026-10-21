"""What Telegram will tell the bot about a chat.

All of it over the Bot API. The moderator bot is an administrator in every
managed chat, which is enough for the title, the photo and the member count —
none of these ever needed the client API, and depending on it was how the
counts came to be empty: that account's session lives on one developer's
machine, so in production there was nothing to ask.

Two calls, because Telegram splits them: `getChat` carries the title and photo,
`getChatMemberCount` carries the number.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram import Bot

logger = get_logger("chats.metadata")

# A public username, the one form of chat link Telegram resolves for a bot that
# is not in the chat; an invite opens only for whoever joins through it. Taken
# as people paste it: "@name", "name", "t.me/name" or the full link.
_USERNAME = re.compile(r"^(?:@|(?:https?://)?(?:t\.me|telegram\.me)/)?(?P<username>[A-Za-z][\w]{3,31})/?$")


def username_of(link: str) -> str | None:
    """The username a pasted link names, or None when it names no public chat."""
    match = _USERNAME.match(link.strip())
    return match["username"] if match else None


async def ask[T](call: Callable[[], Awaitable[T]]) -> T:
    """Make a call, waiting out one "retry after" from flood control.

    Only one: a second refusal means the bot is still over its limit, and the
    caller would rather skip a chat than hold the whole tick.
    """
    try:
        return await call()
    except TelegramRetryAfter as err:
        await asyncio.sleep(err.retry_after)
        return await call()


@dataclass(frozen=True)
class ChatMetadata:
    """What one `getChat` answered with.

    A chat can have a title and no photo. `getChat` answering without a photo
    means there is none now, which is a fact to act on; not answering at all is
    what `fetch_metadata` returning None is for.

    `photo_file_id` is the large size, kept for the console. The catalog shows
    the small one (160 px, plenty for a 44 px avatar on a 3x screen), and its
    unique id is what tells a new photo from the one already stored.
    """

    title: str | None
    photo_file_id: str | None
    avatar_file_id: str | None = None
    avatar_unique_id: str | None = None


def _text(value: object) -> str | None:
    """A string Telegram sent, or None: a field it left out is not a field to guess at."""
    return value if isinstance(value, str) and value else None


async def fetch_metadata(*, bot: Bot, chat_id: int, username: str | None = None) -> ChatMetadata | None:
    """Ask Telegram about a chat. None when it would not say.

    Errors are swallowed to None rather than raised: a chat the bot was removed
    from is an ordinary event on a loop over forty-five of them, and one going
    quiet must not stop the rest.

    A chat the bot is not in is asked about by its public username when there is
    one: Telegram answers `getChat("@name")` for any public group or channel,
    photo included, and refuses the numeric id to a bot that is not a member.
    Asked second, so the id remains the answer wherever the bot does belong.
    """
    try:
        chat = await ask(lambda: bot.get_chat(chat_id))
    except TelegramAPIError as err:
        logger.warning("get_chat_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        if username is None:
            return None
        try:
            chat = await ask(lambda: bot.get_chat(f"@{username}"))
        except TelegramAPIError as err:
            logger.warning(
                "get_chat_by_username_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__
            )
            return None

    photo = getattr(chat, "photo", None)
    return ChatMetadata(
        title=chat.title,
        photo_file_id=_text(getattr(photo, "big_file_id", None)),
        avatar_file_id=_text(getattr(photo, "small_file_id", None)),
        avatar_unique_id=_text(getattr(photo, "small_file_unique_id", None)),
    )


async def fetch_member_count(*, bot: Bot, chat_id: int) -> int | None:
    """How many people are in the chat right now. None when Telegram would not say.

    None and zero are different answers and stay different all the way to the
    page: one means nobody is there, the other means we did not find out.
    """
    try:
        return await ask(lambda: bot.get_chat_member_count(chat_id))
    except TelegramAPIError as err:
        logger.warning("get_chat_member_count_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return None
