"""!welcome command — set per-chat welcome message."""

from aiogram import Router, types
from aiogram.filters import Command

from app.db.repositories import ChatRepository

router = Router()

_USAGE = (
    "Напишите приветствие после команды: <code>!welcome Добро пожаловать! Правила — в закрепе.</code>\n"
    "Жирный, курсив и ссылки сохранятся."
)


@router.message(Command("welcome", prefix="!/"))
async def welcome_change(message: types.Message, chat_repo: ChatRepository) -> None:
    # The HTML Telegram renders from the message's own entities: the admin's
    # formatting survives, and a `<` they typed is escaped. The raw text was
    # stored and sent as HTML, so one typo broke the greeting for every join.
    welcome_message = (message.html_text or "").partition(" ")[2].strip()
    if not welcome_message:
        await message.answer(_USAGE)
        return
    await chat_repo.update_welcome_message(message.chat.id, welcome_message)
    await message.answer("<b>Приветствие сохранено и включено.</b> Так его увидят новые участники:")
    await message.answer(welcome_message)
    await message.delete()
