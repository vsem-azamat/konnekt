"""The retired bots, kept only to say where Konnekt went.

Konnekt has moved address more than once: @student_cz_bot was the catalog's
bot before everything moved into the moderator, and @konnekt_moder_bot was the
moderator until a new bot replaced it (a username cannot be changed). People
still write to the old ones. Each retired token that is configured polls here, next to the main bot,
and answers every private message with the new address. It does nothing else;
switching one off is removing its token.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    Message,
)
from aiogram.utils.token import TokenValidationError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("moved")

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


async def retire_profile(bot: Bot) -> None:
    """Take down what Telegram keeps on the bot from when it was current.

    Its Mini App button would sign in with this bot's token, which the API no
    longer accepts, and its commands lead nowhere; neither reaches the message
    saying where Konnekt went. Logged, not raised: the bot still answers without it.
    """
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        for scope in (
            BotCommandScopeDefault(),
            BotCommandScopeAllPrivateChats(),
            BotCommandScopeAllGroupChats(),
            BotCommandScopeAllChatAdministrators(),
        ):
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logger.warning("retired_profile_not_reset", bot=bot.id, error=str(e))


def build_moved_bots() -> list[tuple[Bot, Dispatcher]]:
    """Each retired bot with a dispatcher of its own, none when no token is configured.

    Of its own because a dispatcher polls one bot at a time, and a router
    belongs to one dispatcher.
    """
    built = []
    for position, token in enumerate(settings.telegram.retired_tokens, start=1):
        try:
            bot = Bot(token=token)
        except TokenValidationError:
            # Here, before anything is contained, it would take moderation down.
            # The position, never the token: it is a secret.
            logger.error("retired_token_malformed", position=position)
            continue
        dp = Dispatcher()
        dp.include_router(build_router())
        dp.startup.register(retire_profile)
        built.append((bot, dp))
    return built
