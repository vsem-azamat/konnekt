"""!mute / !unmute commands."""

from aiogram import Bot, Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ModerationEventAction
from app.core.logging import get_logger
from app.db.repositories import AdminRepository
from app.moderation.mute_permissions import MUTED, UNMUTED
from app.presentation.telegram.handlers.moderation._common import (
    author_of,
    not_a_person_error,
    record_reply_target,
    replied_message,
    reply_required_error,
    untouchable,
)
from app.presentation.telegram.utils import other

logger = get_logger("handler.moderation.mute")
router = Router()


@router.message(Command("mute", prefix="!/"))
async def mute_user(message: types.Message, bot: Bot, db: AsyncSession, admin_repo: AdminRepository) -> None:
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("замутить"))
        await message.delete()
        return

    target = author_of(reply)
    if target is None:
        await message.answer(not_a_person_error())
        return
    actor = message.from_user.id if message.from_user else None
    if reason := await untouchable(bot, admin_repo, chat_id=message.chat.id, actor_id=actor, target_id=target.id):
        await message.answer(reason)
        return

    mute_guide = (
        "Для мута пользователя используйте команду в формате:\n\n"
        "<code>!mute [время] [единица времени]</code>\n\n"
        "Примеры:\n<code>!mute 5m</code> - на 5 минут\n"
        "<code>!mute 1h</code> - на 1 час\n"
        "<code>!mute 1d</code> - на 1 день\n"
        "<code>!mute 1w</code> - на 1 неделю"
    )

    try:
        if not message.text:
            await message.answer("Команда не может быть пустой.")
            return
        mute_duration = other.calculate_mute_duration(message.text)
    except Exception:
        answer = await message.answer(f"Мне не удалось распознать время мута!\n\n{mute_guide}")
        await message.delete()
        other.sleep_and_delete(answer, 10)
        return

    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=MUTED,
            use_independent_chat_permissions=True,
            until_date=mute_duration.until_date,
        )
        await record_reply_target(
            message,
            db,
            ModerationEventAction.MUTE,
            detail=f"{mute_duration.time} {mute_duration.unit}",
        )
        mention = other.get_user_mention(target)
        text_mute = (
            f"{mention} в муте на {mute_duration.time} {mute_duration.unit}!\n\n"
            f"Дата размута: {mute_duration.formatted_until_date()}"
        )
        await reply.reply(text_mute)
        await message.delete()
    except Exception as err:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        logger.error(
            "mute_failed",
            error=str(err),
            user_id=target.id,
            chat_id=message.chat.id,
        )


@router.message(Command("unmute", prefix="!/"))
async def unmute_user(message: types.Message, bot: Bot, db: AsyncSession) -> None:
    reply = replied_message(message)
    if reply is None:
        await message.answer(reply_required_error("размутить"))
        await message.delete()
        return

    target = author_of(reply)
    if target is None:
        await message.answer(not_a_person_error())
        return

    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=UNMUTED,
            use_independent_chat_permissions=True,
        )
        await record_reply_target(message, db, ModerationEventAction.UNMUTE)
        mention = other.get_user_mention(target)
        await message.answer(f"Пользователь {mention} размучен!")
    except Exception as err:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        logger.error(
            "unmute_failed",
            error=str(err),
            user_id=target.id,
            chat_id=message.chat.id,
        )
