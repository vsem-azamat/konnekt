"""What Telegram's updates say about the chats the bot is in, recorded before anything acts on them.

A middleware rather than a handler: aiogram gives a membership update to the
first handler whose filters match, and a recording handler would take updates
from the greeting and the captcha, or lose them to them. Here every update
passes, in any chat the bot has seen, approved or not.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, types
from aiogram.types import TelegramObject

from app.chats import bot_rights
from app.core.logging import get_logger
from app.core.time import as_naive_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("middleware.chat_state")


class ChatStateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        mine = event.my_chat_member if isinstance(event, types.Update) else None
        if mine is not None and mine.chat.type in ("group", "supergroup"):
            db: AsyncSession = data["db"]
            try:
                await bot_rights.record(
                    db, mine.chat.id, mine.new_chat_member, at=as_naive_utc(mine.date), by=mine.from_user.id
                )
            except Exception:
                # Recording is never a reason to drop the update; the daily check catches up.
                logger.exception("bot_rights_not_recorded", chat_id=mine.chat.id)
                await db.rollback()
        return await handler(event, data)
