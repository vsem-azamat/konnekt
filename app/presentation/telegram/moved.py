"""The retired bots, kept only to say where Konnekt went.

Konnekt has moved address more than once: @student_cz_bot was the catalog's
bot before everything moved into the moderator, and @konnekt_moder_bot was the
moderator before it moved to a new username. People still write to the old
ones. Each retired token that is configured polls here, next to the main bot,
and answers every private message with the new address. It does nothing else;
switching one off is removing its token.
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


def build_moved_bots() -> list[tuple[Bot, Dispatcher]]:
    """Each retired bot with a dispatcher of its own, none when no token is configured.

    Of its own because a dispatcher polls one bot at a time, and a router
    belongs to one dispatcher.
    """
    built = []
    for token in settings.telegram.retired_tokens:
        dp = Dispatcher()
        dp.include_router(build_router())
        built.append((Bot(token=token), dp))
    return built
