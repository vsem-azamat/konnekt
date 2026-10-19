"""The retired catalog bot, kept only to say where Konnekt went.

@student_cz_bot was the catalog's bot before everything moved into this one,
and people still write to it. When its token is configured it polls here, next
to the main bot, and answers every private message with the new address. It
does nothing else; switching it off is removing the token.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings

MOVED_TEXT = "Konnekt переехал: каталог, чаты и помощь с учёбой теперь в @{username}. Нажмите там /start."


async def point_to_konnekt(message: Message, konnekt_username: str) -> None:
    await message.answer(
        MOVED_TEXT.format(username=konnekt_username),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Открыть @{konnekt_username}", url=f"https://t.me/{konnekt_username}")]
            ]
        ),
    )


def build_router() -> Router:
    router = Router(name="moved")
    router.message.register(point_to_konnekt, F.chat.type == "private")
    return router


def build_moved_bot() -> tuple[Bot, Dispatcher] | None:
    """The retired bot and its one handler, or None when no token is configured."""
    if not settings.telegram.retired_token:
        return None
    dp = Dispatcher()
    dp.include_router(build_router())
    return Bot(token=settings.telegram.retired_token), dp
