import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, Bot, types
from aiogram.enums import ChatMemberStatus
from aiogram.types import TelegramObject

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.db.repositories import UserRepository

logger = get_logger("middleware.blacklist")

# TTL cache for blocked user IDs (same pattern as ManagedChatsMiddleware)
_blacklist_cache: tuple[set[int], float] | None = None
_CACHE_TTL = 300  # 5 minutes

# Statuses that put the user back in the room. Banning is itself a chat_member
# update (-> KICKED), so reacting only to these keeps the ban from feeding back.
_PRESENT_STATUSES = frozenset({ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED})


def invalidate_blacklist_cache() -> None:
    """Invalidate the blacklist cache so next check re-fetches from DB."""
    global _blacklist_cache  # noqa: PLW0603
    _blacklist_cache = None


async def _still_blocked(user_repo: "UserRepository", user_id: int) -> bool:
    """Confirm a cached id against its row before acting on it.

    The console unbans from the webapi process, whose reset of this cache cannot
    reach the bot, and the MCP unblacklist tool does not reset it either. Without
    the check a person let back in would be banned again on their first message
    until the cache expired. Only ids already in the
    cache pay for the query, and those are few.
    """
    user = await user_repo.get_by_id(user_id)
    if user is not None and user.blocked:
        return True
    invalidate_blacklist_cache()
    return False


class BlacklistMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        global _blacklist_cache  # noqa: PLW0603

        bot: Bot = data["bot"]
        user_repo: UserRepository = data["user_repo"]

        now = time.monotonic()
        if _blacklist_cache is not None and _blacklist_cache[1] > now:
            blacklisted_ids = _blacklist_cache[0]
        else:
            blacklisted_users = await user_repo.get_blocked_users()
            blacklisted_ids = {user.id for user in blacklisted_users}
            _blacklist_cache = (blacklisted_ids, now + _CACHE_TTL)

        if (
            isinstance(event, types.Message)
            # Sent as a channel or anonymously: from_user is Telegram's stand-in,
            # shared by every such message, not the person who wrote it.
            and event.sender_chat is None
            and event.from_user
            and event.from_user.id in blacklisted_ids
        ):
            if not await _still_blocked(user_repo, event.from_user.id):
                return await handler(event, data)
            if event.chat.type not in ("group", "supergroup"):
                # A private chat has nobody to ban anyone from; it is refused.
                return None
            try:
                await bot.ban_chat_member(event.chat.id, event.from_user.id)
            except Exception as e:
                logger.error("ban_failed", user_id=event.from_user.id, error=str(e), exc_info=True)
            try:
                await event.delete()
            except Exception as e:
                logger.error("delete_failed", user_id=event.from_user.id, error=str(e), exc_info=True)
            return None  # Stop further handler processing for blacklisted user

        if isinstance(event, types.ChatMemberUpdated):
            joining = event.new_chat_member.user
            if (
                event.new_chat_member.status in _PRESENT_STATUSES
                and joining.id in blacklisted_ids
                and await _still_blocked(user_repo, joining.id)
            ):
                try:
                    await bot.ban_chat_member(event.chat.id, joining.id)
                except Exception as e:
                    logger.error(
                        "ban_on_join_failed", user_id=joining.id, chat_id=event.chat.id, error=str(e), exc_info=True
                    )
                return None

        return await handler(event, data)
