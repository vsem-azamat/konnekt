"""Commands that act on a message: !kick !del !purge !pin !unpin !info.

All reply-driven — the target is whatever the admin replied to, which is how
these read in a live chat. Each refuses out loud when there is nothing to act
on; a moderation command that silently does nothing teaches an admin to distrust
the bot.
"""

from aiogram import Bot, Router, types
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ModerationEventAction
from app.core.logging import get_logger
from app.core.text import escape_html
from app.db.models import User
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

logger = get_logger("handler.moderation.messages")
router = Router()

# A reply reaching further back than this is a misplaced reply, not a request to
# erase an afternoon. Telegram also caps deleteMessages at 100 per call.
MAX_PURGE = 100


@router.message(Command("kick", prefix="!/"))
async def kick_user(message: types.Message, bot: Bot, db: AsyncSession, admin_repo: AdminRepository) -> None:
    """Remove a member without a lasting ban.

    Telegram has no kick: banning and immediately unbanning removes the person
    while leaving them free to rejoin, which is what "kick" means everywhere
    else. ``only_if_banned`` keeps the second call from lifting an older ban
    that was placed deliberately.
    """
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("удалить из чата"))
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
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await record_reply_target(message, db, ModerationEventAction.KICK)
        await message.answer(f"Пользователь {other.get_user_mention(target)} удалён из чата")
    except Exception as err:
        logger.error("kick_failed", error=str(err), user_id=target.id, chat_id=message.chat.id)
        other.sleep_and_delete(await message.answer("Что-то пошло не так. Попробуйте позже."), 10)

    await message.delete()


@router.message(Command("del", prefix="!/"))
async def delete_message(message: types.Message, bot: Bot) -> None:
    """Delete the message this command replies to."""
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("удалить"))
        return

    try:
        await bot.delete_message(message.chat.id, reply.message_id)
    except Exception as err:
        logger.error("delete_failed", error=str(err), chat_id=message.chat.id)
        other.sleep_and_delete(await message.answer("Не удалось удалить сообщение."), 10)

    await message.delete()


@router.message(Command("purge", prefix="!/"))
async def purge_messages(message: types.Message, bot: Bot) -> None:
    """Delete everything from the replied-to message up to this command."""
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("удалить пачкой (ответом на первое сообщение)"))
        return

    first = reply.message_id
    span = message.message_id - first + 1
    if span > MAX_PURGE:
        await message.answer(f"Слишком большой диапазон: {span} сообщений, максимум {MAX_PURGE}.")
        return

    try:
        await bot.delete_messages(message.chat.id, list(range(first, message.message_id + 1)))
    except Exception as err:
        # Telegram refuses the whole batch if any message is older than 48h.
        logger.error("purge_failed", error=str(err), chat_id=message.chat.id, span=span)
        other.sleep_and_delete(
            await message.answer("Не удалось удалить пачку — возможно, сообщения старше 48 часов."), 10
        )


@router.message(Command("pin", prefix="!/"))
async def pin_message(message: types.Message, bot: Bot) -> None:
    """Pin the replied-to message without notifying everyone."""
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("закрепить"))
        return

    try:
        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=reply.message_id,
            # Pinning notifies every member by default, which is rarely what a
            # moderator wants from a housekeeping action.
            disable_notification=True,
        )
    except Exception as err:
        logger.error("pin_failed", error=str(err), chat_id=message.chat.id)
        other.sleep_and_delete(await message.answer("Не удалось закрепить сообщение."), 10)

    await message.delete()


@router.message(Command("unpin", prefix="!/"))
async def unpin_message(message: types.Message, bot: Bot) -> None:
    """Unpin the replied-to message."""
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("открепить"))
        return

    try:
        await bot.unpin_chat_message(chat_id=message.chat.id, message_id=reply.message_id)
    except Exception as err:
        logger.error("unpin_failed", error=str(err), chat_id=message.chat.id)
        other.sleep_and_delete(await message.answer("Не удалось открепить сообщение."), 10)

    await message.delete()


@router.message(Command("info", prefix="!/"))
async def user_info(message: types.Message, db: AsyncSession) -> None:
    """Show what is on file for the replied-to user."""
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("посмотреть"))
        return
    target = author_of(reply)
    if target is None:
        await message.answer(not_a_person_error())
        return

    stored = await db.scalar(select(User).where(User.id == target.id))

    lines = [
        f"<b>{escape_html(target.full_name)}</b>",
        f"ID: <code>{target.id}</code>",
    ]
    if target.username:
        lines.append(f"Username: @{escape_html(target.username)}")
    if stored is None:
        lines.append("\nВ базе нет — ещё ничего не писал в наших чатах.")
    else:
        lines.append(f"\nВ чёрном списке: {'да' if stored.blocked else 'нет'}")
        lines.append(f"Первая запись: {stored.created_at:%Y-%m-%d}")

    await message.answer("\n".join(lines))
