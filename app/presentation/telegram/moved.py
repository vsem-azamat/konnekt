"""The retired bots, kept only to say where Konnekt went.

Konnekt has moved address more than once: @student_cz_bot was the catalog's
bot before everything moved into the moderator, and @konnekt_moder_bot was the
moderator until a new bot replaced it (a username cannot be changed). People
still write to the old ones. Each retired token that is configured polls here, next to the main bot,
and answers every private message with the new address. It does nothing else;
switching one off is removing its token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
from app.core.enums import Touchpoint
from app.core.logging import get_logger
from app.presentation.telegram.middlewares.audience import AudienceMiddleware
from app.presentation.telegram.profile import LANGUAGES

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("moved")

MOVED_TEXT = "Konnekt переехал: каталог, чаты и помощь с учёбой теперь в @{username}. Нажмите там /start."
MOVED_SHORT_TEXT = "Konnekt переехал: теперь @{username}"


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


async def retire_profile(bot: Bot, konnekt_username: str) -> None:
    """Replace what Telegram keeps on the bot from when it was current.

    Its Mini App button would sign in with this bot's token, which the API no
    longer accepts, its commands lead nowhere, and its description still says
    to press that button. Each step stands alone, as in `profile.py`, and is
    logged rather than raised: the bot still answers without it.
    """
    username = konnekt_username
    scopes = (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    )
    steps: list[tuple[str, Awaitable[object]]] = [
        ("menu_button", bot.set_chat_menu_button(menu_button=MenuButtonCommands())),
        *((f"commands:{scope.type.value}", bot.delete_my_commands(scope=scope)) for scope in scopes),
        ("description", bot.set_my_description(description=MOVED_TEXT.format(username=username))),
        (
            "short_description",
            bot.set_my_short_description(short_description=MOVED_SHORT_TEXT.format(username=username)),
        ),
    ]
    # Telegram shows a language's own text before the default, and the live bot
    # writes one for each of these. Emptied, they fall back to the notice above.
    for language in LANGUAGES:
        steps += [
            *(
                (f"commands:{scope.type.value}:{language}", bot.delete_my_commands(scope=scope, language_code=language))
                for scope in scopes
            ),
            (f"description:{language}", bot.set_my_description(description="", language_code=language)),
            (
                f"short_description:{language}",
                bot.set_my_short_description(short_description="", language_code=language),
            ),
        ]
    for name, step in steps:
        try:
            await step
        except Exception as e:
            logger.warning("retired_profile_step_failed", bot=bot.id, step=name, error=str(e), exc_info=True)


def build_moved_bots(session_maker: async_sessionmaker[AsyncSession]) -> list[tuple[Bot, Dispatcher]]:
    """Each retired bot with a dispatcher of its own, none when no token is configured.

    Of its own because a dispatcher polls one bot at a time, and a router
    belongs to one dispatcher. Whoever still writes to one is kept in the
    audience, as somebody who came to Konnekt by an old address.
    """
    built = []
    for position, token in enumerate(settings.telegram.retired_tokens, start=1):
        if token == settings.telegram.token:
            # A second poller on the main bot would take turns with it for moderation's updates.
            logger.warning("retired_token_is_current", position=position)
            continue
        try:
            bot = Bot(token=token)
        except TokenValidationError:
            # Here, before anything is contained, it would take moderation down.
            # The position, never the token: it is a secret.
            logger.error("retired_token_malformed", position=position)
            continue
        dp = Dispatcher()
        dp.update.outer_middleware(AudienceMiddleware(session_maker, Touchpoint.MOVED_BOT, reach=False))
        dp.include_router(build_router())
        dp.startup.register(retire_profile)
        built.append((bot, dp))
    return built
