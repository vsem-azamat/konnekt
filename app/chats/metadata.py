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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram import Bot

logger = get_logger("chats.metadata")


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

    Both fields are optional and independently so: a chat can have a title and
    no photo, and a caller must be able to leave what it did not learn alone
    rather than overwrite it with a null.
    """

    title: str | None
    photo_file_id: str | None


async def fetch_metadata(*, bot: Bot, chat_id: int) -> ChatMetadata | None:
    """Ask Telegram about a chat. None when it would not say.

    Errors are swallowed to None rather than raised: a chat the bot was removed
    from is an ordinary event on a loop over forty-five of them, and one going
    quiet must not stop the rest.
    """
    try:
        chat = await ask(lambda: bot.get_chat(chat_id))
    except TelegramAPIError as err:
        logger.warning("get_chat_failed", chat_id=chat_id, error=str(err))
        return None

    photo = getattr(chat, "photo", None)
    return ChatMetadata(
        title=chat.title,
        photo_file_id=getattr(photo, "big_file_id", None) if photo is not None else None,
    )


async def fetch_member_count(*, bot: Bot, chat_id: int) -> int | None:
    """How many people are in the chat right now. None when Telegram would not say.

    None and zero are different answers and stay different all the way to the
    page: one means nobody is there, the other means we did not find out.
    """
    try:
        return await ask(lambda: bot.get_chat_member_count(chat_id))
    except TelegramAPIError as err:
        logger.warning("get_chat_member_count_failed", chat_id=chat_id, error=str(err))
        return None
