from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ChatLinkRepository


async def get_chat_buttons(db: AsyncSession) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    chat_links_repo = ChatLinkRepository(db)
    chats = await chat_links_repo.get_chat_links()
    for chat in chats:
        builder.add(InlineKeyboardButton(text=chat.text, url=chat.link))
    builder.adjust(2)
    return builder
