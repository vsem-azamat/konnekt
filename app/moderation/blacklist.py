import asyncio

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotAPersonError, ProtectedUserError
from app.core.logging import get_logger
from app.db.repositories import (
    ChatRepository,
    MessageRepository,
    UserRepository,
)

logger = get_logger("moderation")


# Telegram's stand-ins on messages no person signed: posts sent as a channel,
# anonymous admins, and posts forwarded from a linked channel. Each is shared by
# every such message, so acting on one acts on all of them, everywhere.
STAND_IN_SENDERS = frozenset({136817688, 1087968824, 777000})


def is_stand_in(user_id: int) -> bool:
    return user_id in STAND_IN_SENDERS


def is_protected(user_id: int) -> bool:
    """A super admin: never blacklisted, by any caller.

    A blacklisted account loses every message, its private ones to the bot
    included, so a super admin on the list would lose the bot itself.
    """
    return user_id in settings.admin.super_admins


async def _approved_chat_ids(db: AsyncSession) -> list[int]:
    """The chats a blacklist entry acts in.

    The bot records every group it sits in, other people's included; acting in
    one nobody approved overrules its owner (docs/invariants.md, Approval).
    """
    return [chat.id for chat in await ChatRepository(db).get_chats() if chat.is_approved]


async def add_to_blacklist(
    db: AsyncSession,
    bot: Bot,
    id_tg: int,
    revoke_messages: bool | None = None,
) -> None:
    if is_protected(id_tg):
        raise ProtectedUserError(id_tg)
    if is_stand_in(id_tg):
        raise NotAPersonError(id_tg)
    user_repo = UserRepository(db)
    message_repo = MessageRepository(db)
    await user_repo.add_to_blacklist(id_tg)
    approved = await _approved_chat_ids(db)

    async def ban_user(chat_id: int) -> None:
        try:
            await bot.ban_chat_member(chat_id, id_tg, revoke_messages=revoke_messages)
        except Exception as err:
            logger.warning(
                f"Failed to ban user {id_tg} in chat {chat_id}.\n"
                f"Maybe the user is already banned or not in the chat.\n"
                f"Error: {err}"
            )

    await asyncio.gather(*(ban_user(chat_id) for chat_id in approved))

    if not revoke_messages:
        return

    # Deliberately outside the fan-out above. Every recorded message names the
    # one chat it was written in, so deleting it there is a single call — but
    # nested inside a loop over chats it became that call once per chat, which
    # on forty-five chats and a few hundred messages is thousands of requests,
    # all but a fraction of them doomed, spent while an administrator waits for
    # a spammer to disappear.
    for message in await message_repo.get_user_messages(id_tg):
        # A group counts only when approved; a message whose group has no row
        # (older history) stays. The private chat with the bot is not a group.
        if message.chat_id < 0 and message.chat_id not in approved:
            continue
        try:
            await bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        except Exception as err:
            # Telegram refuses routinely here — a message already gone, or older
            # than it allows. One refusal says nothing about the next.
            logger.warning(f"Failed to delete message {message.message_id} in chat {message.chat_id}.\nError: {err}")


async def remove_from_blacklist(db: AsyncSession, bot: Bot, id_tg: int) -> None:
    user_repo = UserRepository(db)

    await user_repo.remove_from_blacklist(id_tg)
    approved = await _approved_chat_ids(db)

    async def unban_user(chat_id: int) -> None:
        try:
            # Without only_if_banned, Telegram removes a current member.
            await bot.unban_chat_member(chat_id, id_tg, only_if_banned=True)
        except Exception as err:
            logger.warning(f"Failed to unban user {id_tg} in chat {chat_id}.\nError: {err}")

    await asyncio.gather(*(unban_user(chat_id) for chat_id in approved))
