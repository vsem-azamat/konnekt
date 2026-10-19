from aiogram import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import (
    get_chat_repository,
    get_message_repository,
    get_user_repository,
)


async def save_message(db: AsyncSession, message: types.Message, *, edited: bool = False) -> None:
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    message_id = message.message_id
    message_text = message.text or message.caption
    message_info = message.model_dump(
        exclude_defaults=True,
        exclude_none=True,
        exclude={"contact", "location", "venue", "passport_data", "web_app_data"},
    )

    message_repo = get_message_repository(db)
    await message_repo.add_message(chat_id, user_id, message_id, message_text, message_info, replace=edited)


async def merge_user(db: AsyncSession, user: types.User) -> None:
    # Only profile fields: never overwrite blocked / verify.
    await get_user_repository(db).upsert_profile(
        user.id, username=user.username, first_name=user.first_name, last_name=user.last_name
    )


async def merge_chat(db: AsyncSession, chat: types.Chat) -> None:
    chat_repo = get_chat_repository(db)
    await chat_repo.merge_chat(
        id_tg_chat=chat.id,
        title=chat.title,
        is_forum=chat.is_forum,
    )
