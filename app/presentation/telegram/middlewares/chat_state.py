"""What Telegram's updates say about the chats the bot is in, recorded before anything acts on them.

A middleware rather than a handler: aiogram gives a membership update to the
first handler whose filters match, and a recording handler would take updates
from the greeting and the captcha, or lose them to them. Here every update
passes, in any chat the bot has seen, approved or not.

Recorded: the bot's own membership (app/chats/bot_rights.py), everybody
else's (app/chats/members.py), and the people any of these updates, a join
request or a pressed button names. A message's author is the history
middleware's.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, types
from aiogram.types import TelegramObject

from app.chats import bot_rights, members
from app.core.logging import get_logger
from app.core.time import as_naive_utc
from app.moderation import history_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("middleware.chat_state")

_GROUPS = ("group", "supergroup")


def _people(update: types.Update) -> list[types.User]:
    """Everybody the update names, other than a message's author."""
    found: list[types.User] = []
    if change := update.chat_member:
        found += [change.from_user, change.new_chat_member.user]
    if change := update.my_chat_member:
        found.append(change.from_user)
    if request := update.chat_join_request:
        found.append(request.from_user)
    if pressed := update.callback_query:
        found.append(pressed.from_user)
    return list({user.id: user for user in found}.values())


class ChatStateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, types.Update):
            db: AsyncSession = data["db"]
            try:
                await _record(db, event)
            except Exception:
                # Recording is never a reason to drop the update; the daily check catches up.
                logger.exception("chat_state_not_recorded", update_id=event.update_id)
                await db.rollback()
        return await handler(event, data)


async def _record(db: "AsyncSession", update: types.Update) -> None:
    for user in _people(update):
        await history_service.merge_user(db, user)
    mine = update.my_chat_member
    if mine is not None and mine.chat.type in _GROUPS:
        await bot_rights.record(
            db, mine.chat.id, mine.new_chat_member, at=as_naive_utc(mine.date), by=mine.from_user.id
        )
    change = update.chat_member
    if change is not None and change.chat.type in _GROUPS:
        await members.record(db, change.chat.id, change.new_chat_member, at=as_naive_utc(change.date))
