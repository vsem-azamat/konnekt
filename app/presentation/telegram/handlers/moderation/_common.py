"""Shared helpers for the moderation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.enums import ModerationEventSource
from app.moderation.blacklist import is_stand_in

if TYPE_CHECKING:
    from aiogram import Bot, types
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.enums import ModerationEventAction
    from app.db.repositories import AdminRepository


def reply_required_error(action: str) -> str:
    """Standard error when a command should be a reply."""
    return f"Примените команду ответом на сообщение пользователя, которого нужно {action}. 🙏"


def not_a_person_error() -> str:
    """The replied-to message was sent as a channel or by an anonymous admin."""
    return "🚫 Сообщение отправлено от имени канала или анонимного администратора: автора бот не видит."


def replied_message(message: types.Message) -> types.Message | None:
    """The message a command replies to, if it replies to one.

    A message that replies to nothing can still carry a reply: in a forum
    topic it is the topic's first message, and in a linked channel's comments
    it is the channel's post. Either way the command was not aimed at it.
    """
    reply = message.reply_to_message
    if reply is None or reply.forum_topic_created is not None:
        return None
    thread_root = reply.message_id == message.message_thread_id
    if thread_root and (message.is_topic_message or reply.is_automatic_forward):
        return None
    return reply


def author_of(reply: types.Message) -> types.User | None:
    """The person who wrote a message, or None when Telegram does not say."""
    if reply.sender_chat is not None:
        return None
    user = reply.from_user
    if user is None or is_stand_in(user.id):
        return None
    return user


def signer_of(reply: types.Message) -> int | None:
    """Whom a message stands for in the record: its author, or the chat it was sent as."""
    if reply.sender_chat is not None:
        return reply.sender_chat.id
    return reply.from_user.id if reply.from_user else None


async def untouchable(
    bot: Bot,
    admin_repo: AdminRepository,
    *,
    chat_id: int,
    actor_id: int | None,
    target_id: int,
) -> str | None:
    """Why this target may not be acted on in this chat, or None if it may.

    A super admin, the bot itself, and, unless a super admin is asking, a
    moderator of the same chat: one moderator removing another is a dispute
    for the people who appointed them.
    """
    from app.moderation.blacklist import is_protected

    if is_protected(target_id):
        return "🚫 Это главный администратор."
    if target_id == bot.id:
        return "🚫 Это я."
    if not is_protected(actor_id or 0) and await admin_repo.is_admin_in(target_id, chat_id):
        return "🚫 Это модератор этого чата. Снять права может главный администратор."
    return None


async def record_reply_target(
    message: types.Message,
    db: AsyncSession,
    action: ModerationEventAction,
    *,
    target_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Record an action taken against the author of the replied-to message.

    Every command here works the same way — an admin replies to somebody and
    names an action — so both the actor and the target are already on the
    message. Callers reach this only after the guards above have passed, and a
    missing user at that point means the command did nothing worth recording.
    ``target_id`` names the target when it is not the reply's author, as for a
    channel banned as itself.
    """
    from app.moderation import audit

    if target_id is None:
        reply = replied_message(message)
        author = author_of(reply) if reply is not None else None
        target_id = author.id if author is not None else None
    if target_id is None or message.from_user is None:
        return

    await audit.record(
        db,
        action=action,
        source=ModerationEventSource.COMMAND,
        actor_id=message.from_user.id,
        target_user_id=target_id,
        chat_id=message.chat.id,
        detail=detail,
    )
