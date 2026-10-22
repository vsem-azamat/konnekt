"""What Telegram shows about the bot is written by the bot, at startup.

It used to be set by hand, once, and then drifted: the command menu offered
/spam after the handler was gone, and the description still introduced a
moderator of "Czech educational chats" months after the bot became Konnekt.
Set by hand it was also Russian only, so a Czech or Ukrainian Telegram showed
the Russian text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotDescription,
    BotName,
    BotShortDescription,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from app.presentation.telegram import profile
from app.presentation.telegram.handlers import router as handlers_router

from tests.plain_language import slang

if TYPE_CHECKING:
    from aiogram import Bot

pytestmark = pytest.mark.unit

SITE = "https://konnekt.example"
LANGUAGES = [None, "ru", "uk", "cs", "en"]


class FakeBot:
    """Keeps what the Bot API would keep, and counts the writes.

    A mock answering every getter with the same value cannot say whether a
    second run writes anything; this can.
    """

    def __init__(self) -> None:
        self.name = ""
        self.descriptions: dict[str | None, str] = {}
        self.short_descriptions: dict[str | None, str] = {}
        self.commands: dict[tuple[str, str | None], list[BotCommand]] = {}
        self.menu_button: Any = MenuButtonCommands()
        self.writes: list[str] = []
        self.refuse: set[str] = set()

    def _write(self, method: str) -> None:
        if method in self.refuse:
            raise RuntimeError("Telegram said no")
        self.writes.append(method)

    async def get_my_name(self, language_code: str | None = None) -> BotName:
        return BotName(name=self.name)

    async def set_my_name(self, name: str, language_code: str | None = None) -> bool:
        self._write("set_my_name")
        self.name = name
        return True

    async def get_my_description(self, language_code: str | None = None) -> BotDescription:
        return BotDescription(description=self.descriptions.get(language_code, ""))

    async def set_my_description(self, description: str, language_code: str | None = None) -> bool:
        self._write("set_my_description")
        self.descriptions[language_code] = description
        return True

    async def get_my_short_description(self, language_code: str | None = None) -> BotShortDescription:
        return BotShortDescription(short_description=self.short_descriptions.get(language_code, ""))

    async def set_my_short_description(self, short_description: str, language_code: str | None = None) -> bool:
        self._write("set_my_short_description")
        self.short_descriptions[language_code] = short_description
        return True

    async def get_my_commands(self, scope: Any, language_code: str | None = None) -> list[BotCommand]:
        return list(self.commands.get((scope.type, language_code), []))

    async def set_my_commands(self, commands: list[BotCommand], scope: Any, language_code: str | None = None) -> bool:
        self._write("set_my_commands")
        self.commands[(scope.type, language_code)] = list(commands)
        return True

    async def delete_my_commands(self, scope: Any, language_code: str | None = None) -> bool:
        self._write("delete_my_commands")
        self.commands.pop((scope.type, language_code), None)
        return True

    async def get_chat_menu_button(self) -> Any:
        return self.menu_button

    async def set_chat_menu_button(self, menu_button: Any) -> bool:
        self._write("set_chat_menu_button")
        self.menu_button = menu_button
        return True

    async def set_my_default_administrator_rights(self, rights: Any) -> bool:
        self.rights = rights
        return True


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setattr(profile.settings.webapi, "public_url", SITE)


def _handled_commands() -> set[str]:
    names: set[str] = set()

    def walk(router) -> None:
        for handler in router.message.handlers:
            for flt in handler.filters or []:
                if isinstance(flt.callback, Command):
                    names.update(c for c in flt.callback.commands if isinstance(c, str))
        for sub in router.sub_routers:
            walk(sub)

    walk(handlers_router)
    return names


async def _publish(bot: FakeBot) -> None:
    await profile.publish_profile(cast("Bot", bot))


def _names(commands: list[BotCommand]) -> list[str]:
    return [c.command for c in commands]


class TestCommands:
    async def test_every_offered_command_has_a_handler(self, site) -> None:
        bot = FakeBot()

        await _publish(bot)

        offered = {c.command for commands in bot.commands.values() for c in commands}
        assert offered <= _handled_commands()
        assert "spam" not in offered

    async def test_a_private_chat_is_offered_three(self, site) -> None:
        """/chats is the Mini App's catalogue now; typed, it still answers."""
        bot = FakeBot()

        await _publish(bot)

        for language in LANGUAGES:
            assert _names(bot.commands[("default", language)]) == ["start", "help", "contacts"], language
        assert "chats" in _handled_commands()

    async def test_each_language_reads_its_own(self, site) -> None:
        bot = FakeBot()

        await _publish(bot)

        contacts = {lang: bot.commands[("default", lang)][2].description for lang in LANGUAGES}
        assert contacts == {
            None: "Написать нам",
            "ru": "Написать нам",
            "uk": "Написати нам",
            "cs": "Napsat nám",
            "en": "Write to us",
        }

    async def test_a_group_keeps_its_list(self, site) -> None:
        """Telegram reads the group list before any language of the default one."""
        bot = FakeBot()

        await _publish(bot)

        assert _names(bot.commands[("all_group_chats", None)]) == ["report", "chats", "help"]
        assert "report" not in _names(bot.commands[("default", None)])

    async def test_narrower_menus_are_cleared(self, site) -> None:
        """Set by hand, one would win over ours without anybody noticing."""
        bot = FakeBot()
        stale = [BotCommand(command="spam", description="old")]
        bot.commands[("all_private_chats", None)] = stale
        bot.commands[("all_chat_administrators", "uk")] = stale
        bot.commands[("all_group_chats", "cs")] = stale

        await _publish(bot)

        assert ("all_private_chats", None) not in bot.commands
        assert ("all_chat_administrators", "uk") not in bot.commands
        assert ("all_group_chats", "cs") not in bot.commands


class TestText:
    async def test_stale_text_is_replaced_in_every_language(self, site) -> None:
        bot = FakeBot()
        bot.name = "Модератор"
        bot.descriptions[None] = "Я модерирую чешские образовательные чаты!"

        await _publish(bot)

        assert bot.name == profile.NAME
        for language in LANGUAGES:
            assert bot.descriptions[language] == profile.DESCRIPTION[language or "ru"]
            assert bot.short_descriptions[language] == profile.SHORT_DESCRIPTION[language or "ru"]
        assert bot.short_descriptions["cs"] == "Studentské chaty v Česku a pomoc se studiem."

    async def test_a_second_run_writes_nothing(self, site) -> None:
        """Every deploy restarts the bot; Telegram rate-limits setMyName for hours."""
        bot = FakeBot()
        await _publish(bot)
        bot.writes.clear()

        await _publish(bot)

        assert bot.writes == []

    async def test_only_what_differs_is_written(self, site) -> None:
        bot = FakeBot()
        await _publish(bot)
        bot.writes.clear()
        bot.descriptions["uk"] = "старе"

        await _publish(bot)

        assert bot.writes == ["set_my_description"]
        assert bot.descriptions["uk"] == profile.DESCRIPTION["uk"]

    def test_the_description_does_not_give_two_instructions(self) -> None:
        """Under it Telegram draws one button, «Запустить»; the text need not point at it."""
        for text in profile.DESCRIPTION.values():
            assert "/start" not in text

    def test_text_fits_telegram_limits(self) -> None:
        assert len(profile.NAME) <= 64
        for language in profile.LANGUAGES:
            assert len(profile.DESCRIPTION[language]) <= 512
            assert len(profile.SHORT_DESCRIPTION[language]) <= 120
            for command in profile.PRIVATE_COMMANDS[language]:
                assert 1 <= len(command.description) <= 256

    def test_every_language_has_every_text(self) -> None:
        for table in (profile.DESCRIPTION, profile.SHORT_DESCRIPTION, profile.PRIVATE_COMMANDS):
            assert set(table) == set(profile.LANGUAGES)

    def test_members_hear_about_us_not_moderators(self) -> None:
        """What every user reads says what happens to spam, not who does it —
        the same voice as the video."""
        texts = [*profile.DESCRIPTION.values(), *profile.SHORT_DESCRIPTION.values()]
        texts += [c.description for cs in profile.PRIVATE_COMMANDS.values() for c in cs]
        texts += [c.description for c in profile.GROUP_COMMANDS]
        for text in texts:
            assert not any(word in text.lower() for word in ("модер", "moder")), text

    def test_text_is_plain_language(self) -> None:
        """«Přijímačky» is what students call it; the bot names it properly."""
        texts = [profile.NAME, *profile.DESCRIPTION.values(), *profile.SHORT_DESCRIPTION.values()]
        texts += [c.description for cs in profile.PRIVATE_COMMANDS.values() for c in cs]
        texts += [c.description for c in profile.GROUP_COMMANDS]
        for text in texts:
            assert slang(text) == [], text


class TestMenuButton:
    """Telegram keeps this on the bot, not on a message: it stays until something
    writes over it. So the unconfigured cases reset it rather than do nothing — a
    deployment that stops publishing a site would otherwise leave the previous
    one's button pointing at an address that no longer answers."""

    async def test_it_opens_the_chats(self, site) -> None:
        """«Открыть» and the /start button lead to the same place: most people come for a chat."""
        bot = FakeBot()

        await _publish(bot)

        assert isinstance(bot.menu_button, MenuButtonWebApp)
        assert bot.menu_button.web_app.url == f"{SITE}/chats"
        assert bot.menu_button.text == "Открыть"

    async def test_a_trailing_slash_does_not_reach_telegram(self, monkeypatch) -> None:
        monkeypatch.setattr(profile.settings.webapi, "public_url", f"{SITE}/")
        bot = FakeBot()

        await _publish(bot)

        assert bot.menu_button.web_app.url == f"{SITE}/chats"

    async def test_the_old_button_to_help_is_replaced(self, site) -> None:
        bot = FakeBot()
        bot.menu_button = MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=SITE))

        await _publish(bot)

        assert bot.menu_button.web_app.url == f"{SITE}/chats"

    async def test_the_current_button_is_not_rewritten(self, site) -> None:
        bot = FakeBot()
        bot.menu_button = MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=f"{SITE}/chats"))

        await _publish(bot)

        assert "set_chat_menu_button" not in bot.writes

    async def test_no_site_restores_the_command_menu(self, monkeypatch) -> None:
        monkeypatch.setattr(profile.settings.webapi, "public_url", "")
        bot = FakeBot()
        bot.menu_button = MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=SITE))

        await _publish(bot)

        assert isinstance(bot.menu_button, MenuButtonCommands)

    async def test_plain_http_restores_the_command_menu(self, monkeypatch) -> None:
        """Telegram requires https for a Mini App; local development has none."""
        monkeypatch.setattr(profile.settings.webapi, "public_url", "http://localhost:5173")
        bot = FakeBot()
        bot.menu_button = MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=SITE))

        await _publish(bot)

        assert isinstance(bot.menu_button, MenuButtonCommands)


class TestDefaultAdministratorRights:
    async def test_a_new_group_is_asked_for_what_the_commands_use(self, site) -> None:
        """The rights Telegram suggests when somebody adds the bot as an administrator."""
        bot = FakeBot()

        await _publish(bot)

        rights = bot.rights
        granted = {name for name, value in rights.model_dump().items() if value is True}
        refused = {name for name, value in rights.model_dump().items() if value is False}
        # Everything an administrator of a group can hold, except the two that
        # do harm in the wrong hands: anonymity, and appointing administrators,
        # which would let a leaked token hand anybody the chat.
        assert refused == {"is_anonymous", "can_promote_members"}
        assert {"can_delete_messages", "can_restrict_members", "can_invite_users", "can_pin_messages"} <= granted
        assert {"can_change_info", "can_manage_topics", "can_manage_video_chats"} <= granted


class TestOneRefusalDoesNotStopTheRest:
    async def test_a_refused_rename_still_writes_the_menu(self, site) -> None:
        bot = FakeBot()
        bot.refuse = {"set_my_name"}

        await _publish(bot)

        assert ("default", "uk") in bot.commands
        assert isinstance(bot.menu_button, MenuButtonWebApp)

    async def test_a_refused_menu_still_writes_the_rest(self, site) -> None:
        bot = FakeBot()
        bot.refuse = {"set_my_commands", "set_chat_menu_button"}

        await _publish(bot)

        assert bot.descriptions["en"] == profile.DESCRIPTION["en"]
        assert bot.name == profile.NAME


class TestStartupIsNotHeldHostage:
    async def test_a_failed_profile_does_not_stop_the_bot(self, monkeypatch) -> None:
        """Moderation is the job; the profile is a nicety beside it."""
        from unittest.mock import AsyncMock

        from app.presentation.telegram import bot as bot_module

        monkeypatch.setattr(bot_module, "publish_profile", AsyncMock(side_effect=RuntimeError("Telegram said no")))
        bot = AsyncMock()

        await bot_module.on_startup(bot)

        bot.delete_webhook.assert_awaited()

    async def test_a_failed_webhook_clear_does_stop_it(self, monkeypatch) -> None:
        """That one means the bot cannot receive updates at all."""
        from unittest.mock import AsyncMock

        from app.presentation.telegram import bot as bot_module

        published = AsyncMock()
        monkeypatch.setattr(bot_module, "publish_profile", published)
        bot = AsyncMock()
        bot.delete_webhook.side_effect = RuntimeError("Telegram said no")

        with pytest.raises(RuntimeError):
            await bot_module.on_startup(bot)

        published.assert_not_awaited()
