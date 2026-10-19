"""What Telegram shows about the bot: its name, description and command menu.

Telegram keeps all of this on the bot, not in a message, so it is written at
startup like the menu button. Set by hand it drifted: the menu kept /spam after
its handler was gone, and the description kept the bot's old job.
"""

from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

from app.chats.rights import DEFAULT_ADMIN_RIGHTS
from app.core.logging import get_logger

logger = get_logger("telegram.profile")

NAME = "Konnekt"
SHORT_DESCRIPTION = "Студенческие чаты Чехии и помощь с учёбой."
DESCRIPTION = (
    "Konnekt — студенческие чаты Чехии: по университетам, факультетам и общежитиям. "
    "За ними следят модераторы, спам вычищается.\n\n"
    "Здесь же люди, которые помогут с учёбой: репетиторы, вступительные экзамены, нострификация.\n\n"
    "Нажмите «Открыть» или /start."
)

# What /help lists for everybody; moderator commands stay out of the menu,
# because being a Telegram administrator of a chat grants nothing here. Groups
# not yet approved see the group menu too, and the bot answers nothing there:
# hiding it would take a scope per chat.
PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Что здесь есть"),
    BotCommand(command="chats", description="Чаты списком"),
    BotCommand(command="help", description="Команды"),
    BotCommand(command="contacts", description="Связаться"),
]
GROUP_COMMANDS = [
    BotCommand(command="report", description="В ответ на сообщение: позвать модераторов"),
    BotCommand(command="chats", description="Чаты списком"),
    BotCommand(command="help", description="Команды"),
]


async def _set_name(bot: Bot) -> None:
    if (await bot.get_my_name()).name != NAME:
        await bot.set_my_name(name=NAME)


async def _set_description(bot: Bot) -> None:
    if (await bot.get_my_description()).description != DESCRIPTION:
        await bot.set_my_description(description=DESCRIPTION)


async def _set_short_description(bot: Bot) -> None:
    if (await bot.get_my_short_description()).short_description != SHORT_DESCRIPTION:
        await bot.set_my_short_description(short_description=SHORT_DESCRIPTION)


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(commands=PRIVATE_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_my_commands(commands=GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    # A narrower scope set by hand would win over these without anybody noticing.
    await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    await bot.delete_my_commands(scope=BotCommandScopeAllChatAdministrators())


async def _set_admin_rights(bot: Bot) -> None:
    await bot.set_my_default_administrator_rights(rights=DEFAULT_ADMIN_RIGHTS)


# The name goes last: setMyName is rate-limited for hours after a rename.
_STEPS: list[tuple[str, Callable[[Bot], Awaitable[None]]]] = [
    ("commands", _set_commands),
    ("admin_rights", _set_admin_rights),
    ("description", _set_description),
    ("short_description", _set_short_description),
    ("name", _set_name),
]


async def publish_profile(bot: Bot) -> None:
    """Bring the bot's profile in line with this module.

    Text is compared first and written only when it differs, because every
    deploy restarts the bot. Each step stands alone, so one refusal (a rename
    under flood control) does not leave the stale menu in place.
    """
    for name, step in _STEPS:
        try:
            await step(bot)
        except Exception as err:
            logger.warning("profile_step_failed", step=name, error=str(err))
