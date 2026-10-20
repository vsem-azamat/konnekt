"""Two guards, told apart by how far a mistake travels.

:class:`AdminMiddleware` covers commands that spoil one chat — a ban, a mute, a
deleted message. Whoever moderates that chat may run them, and nowhere else.

:class:`SuperAdminMiddleware` covers commands that spoil all forty-five at once:
the shared blacklist, handing out moderator rights, a link into the web console.
Those stay with the accounts named in ``ADMIN_SUPER_ADMINS``, which lives in
configuration rather than the database, so the set of people who can grant power
cannot be changed by writing a row.

Neither guard consults Telegram's own list of chat administrators. That crown
gets handed out so a name appears in the member list.
"""

import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, types
from aiogram.types import TelegramObject

from app.core.config import settings
from app.core.logging import get_logger
from app.moderation.blacklist import is_stand_in
from app.presentation.telegram.utils.other import sleep_and_delete
from app.presentation.telegram.utils.throttle import Throttle

if TYPE_CHECKING:
    from app.db.repositories import AdminRepository

logger = get_logger("middleware.admin")

NOT_ADMIN = "🚫 У вас нет прав на эту команду в этом чате."
NOT_SUPER_ADMIN = "🚫 Эта команда доступна только главным администраторам."


# One answered refusal per person per chat per minute; the rest are only deleted.
_refusals = Throttle(60)


def forget_refusals() -> None:
    _refusals.clear()


async def you_are_not_admin(event: TelegramObject, text: str = NOT_ADMIN) -> None:
    """Say no, then clear both messages away.

    A refusal that stays on screen is a second piece of noise in a chat that
    already has enough, and it invites the next person to try the same command.
    Its removal is scheduled, not awaited: sleeping here held the update's
    database connection, and twenty refused commands held the whole pool.
    """
    if isinstance(event, types.Message):
        # Without delete rights the refusal must still be said.
        with contextlib.suppress(Exception):
            await event.delete()
        sender = event.from_user.id if event.from_user else None
        if not _refusals.allow((sender, event.chat.id)):
            return
        sleep_and_delete(await event.answer(text), 5)


def _actor(event: TelegramObject) -> types.User | None:
    if isinstance(event, (types.Message, types.CallbackQuery)):
        return event.from_user
    return None


def _chat_id(event: TelegramObject) -> int | None:
    """The chat a command was aimed at, or None when there isn't one.

    A callback carries its chat on the message it is attached to, and an
    inaccessible message — one the bot can no longer read — still carries the
    chat id, which is all this needs.
    """
    if isinstance(event, types.Message):
        return event.chat.id
    if isinstance(event, types.CallbackQuery) and event.message is not None:
        return event.message.chat.id
    return None


def is_super_admin(user_id: int) -> bool:
    return user_id in settings.admin.super_admins


class SuperAdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor = _actor(event)
        if actor is not None and is_super_admin(actor.id):
            return await handler(event, data)
        await you_are_not_admin(event, NOT_SUPER_ADMIN)
        return None


class AdminMiddleware(BaseMiddleware):
    """Lets a moderator act, in the chats they were given and no others."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor = _actor(event)
        if actor is None or is_stand_in(actor.id) or (isinstance(event, types.Message) and event.sender_chat):
            # Sent as a channel or anonymously: whoever it is, the bot cannot
            # tell, and a grant to the stand-in would cover all of them.
            await you_are_not_admin(event)
            return None

        if is_super_admin(actor.id):
            return await handler(event, data)

        chat_id = _chat_id(event)
        if chat_id is None:
            await you_are_not_admin(event)
            return None

        admin_repo: AdminRepository = data["admin_repo"]
        if await admin_repo.is_admin_in(actor.id, chat_id):
            return await handler(event, data)

        logger.info("command_refused", user_id=actor.id, chat_id=chat_id)
        await you_are_not_admin(event)
        return None
