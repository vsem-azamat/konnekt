from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware, types
from aiogram.types import TelegramObject
from sqlalchemy import select

from app.chats.migration import follow_upgrade
from app.core.logging import get_logger
from app.db.models import Chat
from app.moderation import history_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger("middleware.managed_chats")


def _group_chat(event: TelegramObject) -> types.Chat | None:
    """The group or supergroup this update concerns, if any.

    Covers messages, membership changes, join requests and button presses
    alike: approval is a property of the chat, not of an update type. Banning
    someone at the door, turning away an applicant or acting on a pressed
    button is as public as answering a command, and each arrives on a
    different carrier. A press carries its chat on the message it is attached
    to, which stays readable as an inaccessible message.
    """
    if not isinstance(event, types.Update):
        return None
    pressed = event.callback_query.message if event.callback_query else None
    carrier: types.Message | types.InaccessibleMessage | types.ChatMemberUpdated | types.ChatJoinRequest | None = (
        event.message or event.edited_message or event.chat_member or event.chat_join_request or pressed
    )
    if carrier is None:
        return None
    if carrier.chat.type not in ["group", "supergroup"]:
        return None
    return carrier.chat


class ManagedChatsMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db: AsyncSession = data["db"]
        chat = _group_chat(event)
        if chat is not None:
            await history_service.merge_chat(db, chat)
            upgraded_from = (
                event.message.migrate_from_chat_id if isinstance(event, types.Update) and event.message else None
            )
            if upgraded_from is not None:
                try:
                    await follow_upgrade(db, old_id=upgraded_from, new_id=chat.id)
                except Exception:
                    # Announced once and never again, so this is the one chance;
                    # an error leaves it to a person, and the update goes on.
                    await db.rollback()
                    logger.exception("chat_upgrade_not_followed", old_id=upgraded_from, new_id=chat.id)
            status = await db.scalar(select(Chat.resource_status).where(Chat.id == chat.id))
            data["chat_resource_status"] = status or Chat.STATUS_DISCOVERED
            data["chat_is_approved"] = status == Chat.STATUS_APPROVED

        return await handler(event, data)


class ApprovedChatGateMiddleware(BaseMiddleware):
    """Stop active bot behavior in discovered or disabled group resources.

    This middleware must run after HistoryMiddleware so passive history capture
    still happens for resources awaiting approval.
    """

    def __init__(self) -> None:
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if _group_chat(event) is not None and not data.get("chat_is_approved", False):
            return None
        return await handler(event, data)
