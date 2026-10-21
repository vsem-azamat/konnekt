"""!ban / !unban commands."""

from aiogram import Bot, Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ModerationEventAction
from app.core.logging import get_logger
from app.core.text import escape_html
from app.db.repositories import AdminRepository
from app.presentation.telegram.handlers.moderation._common import (
    author_of,
    not_a_person_error,
    record_reply_target,
    replied_message,
    reply_required_error,
    untouchable,
)
from app.presentation.telegram.utils import other

logger = get_logger("handler.moderation.ban")
router = Router()


def _posting_channel(message: types.Message, reply: types.Message) -> types.Chat | None:
    """The channel a reply was posted as, if it was; never the chat's own.

    An anonymous admin posts as the group, and a linked channel's posts arrive
    as automatic forwards: banning the group from itself, or from its own
    channel, is not a thing anybody means.
    """
    sender = reply.sender_chat
    if sender is None or sender.id == message.chat.id or sender.type != "channel" or reply.is_automatic_forward:
        return None
    return sender


@router.message(Command("ban", prefix="!/"))
async def ban_user(message: types.Message, bot: Bot, db: AsyncSession, admin_repo: AdminRepository) -> None:
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("забанить"))
        return

    if channel := _posting_channel(message, reply):
        # Banning the stand-in user would leave the channel posting; the
        # channel itself is what Telegram can ban.
        await _act_on_channel(message, bot, db, channel, ban=True)
        return

    target = author_of(reply)
    if target is None:
        await message.answer(not_a_person_error())
        return
    actor = message.from_user.id if message.from_user else None
    if reason := await untouchable(bot, admin_repo, chat_id=message.chat.id, actor_id=actor, target_id=target.id):
        await message.answer(reason)
        return

    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await record_reply_target(message, db, ModerationEventAction.BAN)
        await message.answer(f"Пользователь {other.get_user_mention(target)} забанен")
    except Exception as err:
        error_msg = await message.answer("Что-то пошло не так. Попробуйте позже.")
        logger.error("ban_failed", error=str(err), exc_info=True, user_id=target.id, chat_id=message.chat.id)
        other.sleep_and_delete(error_msg, 10)

    await message.delete()


@router.message(Command("unban", prefix="!/"))
async def unban_user(message: types.Message, bot: Bot, db: AsyncSession) -> None:
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("разбанить"))
        return

    if channel := _posting_channel(message, reply):
        await _act_on_channel(message, bot, db, channel, ban=False)
        return

    target = author_of(reply)
    if target is None:
        await message.answer(not_a_person_error())
        return

    try:
        # Without only_if_banned Telegram's unban removes a current member.
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await record_reply_target(message, db, ModerationEventAction.UNBAN)
        await message.answer(f"Пользователь {other.get_user_mention(target)} разбанен")
    except Exception as err:
        error_msg = await message.answer("Что-то пошло не так. Попробуйте позже.")
        logger.error("unban_failed", error=str(err), exc_info=True, user_id=target.id, chat_id=message.chat.id)
        other.sleep_and_delete(error_msg, 10)

    await message.delete()


async def _act_on_channel(
    message: types.Message, bot: Bot, db: AsyncSession, channel: types.Chat, *, ban: bool
) -> None:
    title = escape_html(channel.title or str(channel.id))
    try:
        if ban:
            await bot.ban_chat_sender_chat(message.chat.id, channel.id)
        else:
            await bot.unban_chat_sender_chat(message.chat.id, channel.id)
        await record_reply_target(
            message,
            db,
            ModerationEventAction.BAN if ban else ModerationEventAction.UNBAN,
            target_id=channel.id,
            detail="канал",
        )
        await message.answer(f"Канал {title} {'забанен' if ban else 'разбанен'}")
    except Exception as err:
        error_msg = await message.answer("Что-то пошло не так. Попробуйте позже.")
        logger.error(
            "channel_ban_failed", error=str(err), exc_info=True, channel_id=channel.id, chat_id=message.chat.id, ban=ban
        )
        other.sleep_and_delete(error_msg, 10)

    await message.delete()
