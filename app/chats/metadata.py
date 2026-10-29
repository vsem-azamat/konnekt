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

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramMigrateToChat, TelegramRetryAfter

from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram import Bot
    from aiogram.types import ChatFullInfo

logger = get_logger("chats.metadata")

# A public username, the one form of chat link Telegram resolves for a bot that
# is not in the chat; an invite opens only for whoever joins through it. Taken
# as people paste it: "@name", "name", "t.me/name" or the full link.
_USERNAME = re.compile(r"^(?:@|(?:https?://)?(?:t\.me|telegram\.me)/)?(?P<username>[A-Za-z][\w]{3,31})/?$")


def username_of(link: str) -> str | None:
    """The username a pasted link names, or None when it names no public chat."""
    match = _USERNAME.match(link.strip())
    return match["username"] if match else None


# Longer waits are not worth holding a tick for. On 2026-10-22 a burst of
# lookups by name earned the bot an 80-minute wait on exactly that call.
LONGEST_RETRY_WAIT_SECONDS = 60


async def ask[T](call: Callable[[], Awaitable[T]]) -> T:
    """Make a call, waiting out one short "retry after" from flood control.

    Only one, and only up to a minute: a second refusal or a longer wait means
    the bot is over its limit, and the caller would rather skip a chat than
    hold the whole tick.
    """
    try:
        return await call()
    except TelegramRetryAfter as err:
        if err.retry_after > LONGEST_RETRY_WAIT_SECONDS:
            raise
        await asyncio.sleep(err.retry_after)
        return await call()


class BotNotInChatError(Exception):
    """Telegram does not know the chat to this bot: "chat not found".

    What a private group answers a bot that was never in it, and what a deleted
    chat answers too; a bot that was kicked hears "Forbidden" instead. Unlike a
    flood or a timeout it will say the same thing an hour later.
    """


def _not_found(err: TelegramAPIError) -> bool:
    return isinstance(err, TelegramBadRequest) and "chat not found" in err.message.lower()


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
    # Telegram's "approve new members". It leaves the field out when off, so
    # an answer without it is False, not unknown.
    join_by_request: bool = False
    username: str | None = None
    # The rest of what `getChat` says that no update announces when it changes.
    description: str | None = None
    chat_type: str | None = None
    is_forum: bool = False
    slow_mode_delay: int | None = None
    permissions: dict[str, bool] | None = None
    has_protected_content: bool = False
    has_hidden_members: bool = False
    has_aggressive_anti_spam_enabled: bool = False
    message_auto_delete_time: int | None = None
    linked_chat_id: int | None = None


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
        # Under flood control a second call only adds to the wait.
        if username is None or isinstance(err, TelegramRetryAfter):
            return None
        try:
            return await fetch_metadata_by_name(bot=bot, chat_id=chat_id, username=username)
        except TelegramRetryAfter:
            return None
    return _metadata_of(chat)


async def fetch_metadata_by_name(*, bot: Bot, chat_id: int, username: str) -> ChatMetadata | None:
    """Ask about a chat by its public name only, for one that refused the bot its id.

    None when Telegram would not say, or when the name now belongs to another
    chat. Raises `TelegramRetryAfter` under a long flood wait, so the caller
    can stop asking by name for the rest of its run.
    """
    try:
        chat = await ask(lambda: bot.get_chat(f"@{username}"))
    except TelegramRetryAfter:
        raise
    except TelegramAPIError as err:
        logger.warning("get_chat_by_username_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return None
    # A name can be dropped and taken by somebody else; what it resolves to
    # now is only this chat if it is the same id and still a group, or a
    # channel listed as one (never a person).
    if chat.id != chat_id or chat.type not in ("group", "supergroup", "channel"):
        logger.warning("get_chat_by_username_other_chat", chat_id=chat_id, found_type=chat.type)
        return None
    return _metadata_of(chat)


def _metadata_of(chat: ChatFullInfo) -> ChatMetadata:
    photo = getattr(chat, "photo", None)
    return ChatMetadata(
        title=chat.title,
        photo_file_id=_text(getattr(photo, "big_file_id", None)),
        avatar_file_id=_text(getattr(photo, "small_file_id", None)),
        avatar_unique_id=_text(getattr(photo, "small_file_unique_id", None)),
        join_by_request=getattr(chat, "join_by_request", None) is True,
        username=_text(getattr(chat, "username", None)),
        description=_text(getattr(chat, "description", None)),
        chat_type=_text(getattr(chat.type, "value", chat.type)),
        # Like join_by_request, Telegram leaves these flags out when they are off.
        is_forum=getattr(chat, "is_forum", None) is True,
        slow_mode_delay=_number(getattr(chat, "slow_mode_delay", None)),
        permissions=_permissions(getattr(chat, "permissions", None)),
        has_protected_content=getattr(chat, "has_protected_content", None) is True,
        has_hidden_members=getattr(chat, "has_hidden_members", None) is True,
        has_aggressive_anti_spam_enabled=getattr(chat, "has_aggressive_anti_spam_enabled", None) is True,
        message_auto_delete_time=_number(getattr(chat, "message_auto_delete_time", None)),
        linked_chat_id=_number(getattr(chat, "linked_chat_id", None)),
    )


def _number(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _permissions(value: object) -> dict[str, bool] | None:
    """What members may do by default, under Telegram's names; None when it did not say."""
    dump = getattr(value, "model_dump", None)
    if dump is None:
        return None
    return {name: flag for name, flag in dump().items() if isinstance(flag, bool)}


class ChatMigratedError(Exception):
    """The group was upgraded to a supergroup, which has an id of its own.

    Telegram answers every call about the old id this way, for good: the old
    group is closed, and the bot meets the new one as a chat it has not seen.
    """

    def __init__(self, chat_id: int, new_chat_id: int) -> None:
        super().__init__(f"chat {chat_id} moved to {new_chat_id}")
        self.chat_id = chat_id
        self.new_chat_id = new_chat_id


async def fetch_member_count(*, bot: Bot, chat_id: int) -> int | None:
    """How many people are in the chat right now. None when Telegram would not say.

    None and zero are different answers and stay different all the way to the
    page: one means nobody is there, the other means we did not find out.

    Raises `BotNotInChatError` when the bot is not in the chat, so the caller can
    stop asking every hour rather than log the same refusal each time, and
    `ChatMigratedError` when the group became a supergroup, so it can stop for good.
    """
    try:
        return await ask(lambda: bot.get_chat_member_count(chat_id))
    except TelegramMigrateToChat as err:
        raise ChatMigratedError(chat_id, err.migrate_to_chat_id) from err
    except TelegramAPIError as err:
        if _not_found(err):
            raise BotNotInChatError(chat_id) from err
        logger.warning("get_chat_member_count_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__)
        return None


async def fetch_member_count_by_name(*, bot: Bot, chat_id: int, username: str) -> int | None:
    """How many people are in a public chat the bot is not in. None when Telegram would not say.

    Telegram tells anyone the size of a public group or channel asked by its
    name, and refuses the id to a bot that is not a member. The answer names no
    chat, so ask only after `fetch_metadata_by_name` found the name still this
    chat's. Raises `TelegramRetryAfter` under a long flood wait, like it.
    """
    try:
        return await ask(lambda: bot.get_chat_member_count(f"@{username}"))
    except TelegramRetryAfter:
        raise
    except TelegramAPIError as err:
        logger.warning(
            "get_chat_member_count_by_username_failed", chat_id=chat_id, error=str(err), error_type=type(err).__name__
        )
        return None
