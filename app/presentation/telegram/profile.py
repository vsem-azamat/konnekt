"""What Telegram shows about the bot: its name, description, command menu and menu button.

Telegram keeps all of this on the bot, not in a message, so it is written at
startup. Set by hand it drifted: the menu kept /spam after its handler was
gone, and the description kept the bot's old job.

Each text is written for the default and for every language below. Telegram
shows the default to anybody whose app speaks another language, so the default
is Russian, as most members are. Translations are approved drafts from the
mockup; a native speaker has yet to read them.
"""

from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

from app.chats.rights import DEFAULT_ADMIN_RIGHTS
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("telegram.profile")

LANGUAGES = ("ru", "uk", "cs", "en")
DEFAULT_LANGUAGE = "ru"

NAME = "Konnekt"
SHORT_DESCRIPTION = {
    "ru": "Студенческие чаты Чехии и помощь с учёбой.",
    "uk": "Студентські чати Чехії та допомога з навчанням.",
    "cs": "Studentské chaty v Česku a pomoc se studiem.",
    "en": "Student chats in Czechia and help with studies.",
}
# Under the description Telegram draws one button, «Запустить»; the text does
# not need to point at it.
DESCRIPTION = {
    "ru": (
        "Konnekt — студенческие чаты Чехии: по университетам, факультетам и общежитиям. "
        "Спам, скам и фишинг из чатов мы вычищаем.\n\n"
        "Здесь же люди, которые помогут с учёбой: репетиторы, подготовка к вступительным экзаменам, нострификация."
    ),
    "uk": (
        "Konnekt — студентські чати Чехії: за університетами, факультетами й гуртожитками. "
        "Спам, скам і фішинг із чатів ми вичищаємо.\n\n"
        "Тут же люди, які допоможуть з навчанням: репетитори, підготовка до вступних іспитів, нострифікація."
    ),
    "cs": (
        "Konnekt — studentské chaty v Česku podle univerzit, fakult a kolejí. "
        "Spam, podvody a phishing z chatů mažeme.\n\n"
        "Najdeš tu i lidi, kteří pomohou se studiem: doučování, příprava na přijímací zkoušky, nostrifikace."
    ),
    "en": (
        "Konnekt — student chats in Czechia, by university, faculty and dorm. "
        "We clean spam, scams and phishing out of the chats.\n\n"
        "Here you will also find people who help with studies: tutors, entrance exam prep, nostrification."
    ),
}

# What /help lists for everybody; moderator commands stay out of the menu,
# because being a Telegram administrator of a chat grants nothing here. /chats
# is left out of the private menu: the catalogue is the Mini App's, and typed,
# /chats still answers. /contacts is named as the line in the Mini App profile.
PRIVATE_COMMANDS = {
    "ru": [
        BotCommand(command="start", description="Что здесь есть"),
        BotCommand(command="help", description="Команды"),
        BotCommand(command="contacts", description="Написать нам"),
    ],
    "uk": [
        BotCommand(command="start", description="Що тут є"),
        BotCommand(command="help", description="Команди"),
        BotCommand(command="contacts", description="Написати нам"),
    ],
    "cs": [
        BotCommand(command="start", description="Co tu najdu"),
        BotCommand(command="help", description="Příkazy"),
        BotCommand(command="contacts", description="Napsat nám"),
    ],
    "en": [
        BotCommand(command="start", description="What is here"),
        BotCommand(command="help", description="Commands"),
        BotCommand(command="contacts", description="Write to us"),
    ],
}
# Default only: Telegram reads the group list before any language of the
# default one. Groups not yet approved see it too, and the bot answers nothing
# there: hiding it would take a scope per chat.
GROUP_COMMANDS = [
    BotCommand(command="report", description="В ответ на сообщение: пожаловаться на него"),
    BotCommand(command="chats", description="Чаты списком"),
    BotCommand(command="help", description="Команды"),
]

MENU_BUTTON_TEXT = "Открыть"

# None is Telegram's default, shown to every language not listed.
_TARGETS: list[str | None] = [None, *LANGUAGES]


def _in(language: str | None) -> str:
    return language or DEFAULT_LANGUAGE


def _changed(item: str, language: str | None = None) -> None:
    logger.info("bot_profile_changed", item=item, language=language or "default")


async def _set_name(bot: Bot) -> None:
    if (await bot.get_my_name()).name != NAME:
        await bot.set_my_name(name=NAME)
        _changed("name")


async def _set_description(bot: Bot) -> None:
    for language in _TARGETS:
        text = DESCRIPTION[_in(language)]
        if (await bot.get_my_description(language_code=language)).description != text:
            await bot.set_my_description(description=text, language_code=language)
            _changed("description", language)


async def _set_short_description(bot: Bot) -> None:
    for language in _TARGETS:
        text = SHORT_DESCRIPTION[_in(language)]
        if (await bot.get_my_short_description(language_code=language)).short_description != text:
            await bot.set_my_short_description(short_description=text, language_code=language)
            _changed("short_description", language)


_Scope = (
    BotCommandScopeDefault
    | BotCommandScopeAllGroupChats
    | BotCommandScopeAllPrivateChats
    | BotCommandScopeAllChatAdministrators
)


def _wanted_commands() -> list[tuple[_Scope, str | None, list[BotCommand]]]:
    wanted: list[tuple[_Scope, str | None, list[BotCommand]]] = []
    for language in _TARGETS:
        wanted.append((BotCommandScopeDefault(), language, PRIVATE_COMMANDS[_in(language)]))
        wanted.append((BotCommandScopeAllGroupChats(), language, GROUP_COMMANDS if language is None else []))
        # A narrower scope set by hand would win over these without anybody noticing.
        wanted.append((BotCommandScopeAllPrivateChats(), language, []))
        wanted.append((BotCommandScopeAllChatAdministrators(), language, []))
    return wanted


def _pairs(commands: list[BotCommand]) -> list[tuple[str, str]]:
    return [(c.command, c.description) for c in commands]


async def _set_commands(bot: Bot) -> None:
    for scope, language, commands in _wanted_commands():
        current = await bot.get_my_commands(scope=scope, language_code=language)
        if _pairs(current) == _pairs(commands):
            continue
        if commands:
            await bot.set_my_commands(commands=commands, scope=scope, language_code=language)
        else:
            await bot.delete_my_commands(scope=scope, language_code=language)
        _changed(f"commands:{scope.type}", language)


def _menu_button() -> MenuButtonWebApp | MenuButtonCommands:
    """The Mini App on «Чаты», where the /start button goes too.

    https is Telegram's requirement for a Mini App, not ours; local development
    runs over http and gets the ordinary command menu. Reset rather than left
    alone: a deployment that turns the public site off would otherwise keep a
    button to an address that no longer answers.
    """
    site = settings.webapi.public_url.rstrip("/")
    if site.startswith("https://"):
        return MenuButtonWebApp(text=MENU_BUTTON_TEXT, web_app=WebAppInfo(url=f"{site}/chats"))
    return MenuButtonCommands()


def _button_key(button: object) -> tuple[str | None, str | None, str | None]:
    web_app = getattr(button, "web_app", None)
    return getattr(button, "type", None), getattr(button, "text", None), web_app.url if web_app else None


async def _set_menu_button(bot: Bot) -> None:
    button = _menu_button()
    if _button_key(await bot.get_chat_menu_button()) != _button_key(button):
        await bot.set_chat_menu_button(menu_button=button)
        _changed("menu_button")


async def _set_admin_rights(bot: Bot) -> None:
    await bot.set_my_default_administrator_rights(rights=DEFAULT_ADMIN_RIGHTS)


# The name goes last: setMyName is rate-limited for hours after a rename.
_STEPS: list[tuple[str, Callable[[Bot], Awaitable[None]]]] = [
    ("menu_button", _set_menu_button),
    ("commands", _set_commands),
    ("admin_rights", _set_admin_rights),
    ("description", _set_description),
    ("short_description", _set_short_description),
    ("name", _set_name),
]


async def publish_profile(bot: Bot) -> None:
    """Bring the bot's profile in line with this module.

    Each value is read first and written only when it differs, because every
    deploy restarts the bot. Each step stands alone, so one refusal (a rename
    under flood control) does not leave the stale menu in place.
    """
    for name, step in _STEPS:
        try:
            await step(bot)
        except Exception as err:
            logger.warning("profile_step_failed", step=name, error=str(err), exc_info=True)
