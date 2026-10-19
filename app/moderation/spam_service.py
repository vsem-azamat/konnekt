from aiogram import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import get_message_repository


async def detect_spam(db: AsyncSession, message: types.Message) -> bool:
    if not message.from_user:
        return False
    text = message.text or message.caption
    if not text:
        return False

    message_repo = get_message_repository(db)
    if await message_repo.has_previous_messages(
        chat_id=message.chat.id, user_id=message.from_user.id, before_message_id=message.message_id
    ):
        return False

    return bool(await message_repo.is_similar_spam_message(text))
