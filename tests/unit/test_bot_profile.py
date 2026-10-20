"""What Telegram shows about the bot is written by the bot, at startup.

It used to be set by hand, once, and then drifted: the command menu offered
/spam after the handler was gone, and the description still introduced a
moderator of "Czech educational chats" months after the bot became Konnekt.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.filters import Command
from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeDefault
from app.presentation.telegram import profile
from app.presentation.telegram.handlers import router as handlers_router

from tests.plain_language import slang

pytestmark = pytest.mark.unit


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


def _bot(*, name: str = "", description: str = "", short: str = "") -> AsyncMock:
    bot = AsyncMock()
    bot.get_my_name.return_value = SimpleNamespace(name=name)
    bot.get_my_description.return_value = SimpleNamespace(description=description)
    bot.get_my_short_description.return_value = SimpleNamespace(short_description=short)
    return bot


def _commands(bot: AsyncMock, scope_type: type) -> list[str]:
    for call in bot.set_my_commands.await_args_list:
        if isinstance(call.kwargs["scope"], scope_type):
            return [c.command for c in call.kwargs["commands"]]
    raise AssertionError(f"no commands set for {scope_type.__name__}")


class TestCommands:
    async def test_every_offered_command_has_a_handler(self) -> None:
        bot = _bot()

        await profile.publish_profile(bot)

        offered = set(_commands(bot, BotCommandScopeDefault)) | set(_commands(bot, BotCommandScopeAllGroupChats))
        assert offered <= _handled_commands()
        assert "spam" not in offered

    async def test_a_group_is_offered_report(self) -> None:
        bot = _bot()

        await profile.publish_profile(bot)

        assert "report" in _commands(bot, BotCommandScopeAllGroupChats)
        assert "report" not in _commands(bot, BotCommandScopeDefault)


class TestText:
    async def test_stale_text_is_replaced(self) -> None:
        bot = _bot(name="Модератор", description="Я модерирую чешские образовательные чаты!", short="old")

        await profile.publish_profile(bot)

        bot.set_my_name.assert_awaited_once_with(name=profile.NAME)
        assert "Konnekt" in bot.set_my_description.await_args.kwargs["description"]
        bot.set_my_short_description.assert_awaited_once_with(short_description=profile.SHORT_DESCRIPTION)

    async def test_current_text_is_not_rewritten(self) -> None:
        """Telegram rate-limits setMyName hard; a restart must not spend it."""
        bot = _bot(name=profile.NAME, description=profile.DESCRIPTION, short=profile.SHORT_DESCRIPTION)

        await profile.publish_profile(bot)

        bot.set_my_name.assert_not_awaited()
        bot.set_my_description.assert_not_awaited()
        bot.set_my_short_description.assert_not_awaited()

    def test_text_fits_telegram_limits(self) -> None:
        assert len(profile.NAME) <= 64
        assert len(profile.DESCRIPTION) <= 512
        assert len(profile.SHORT_DESCRIPTION) <= 120

    def test_members_hear_about_us_not_moderators(self) -> None:
        """What every user reads says what happens to spam, not who does it —
        the same voice as the video."""
        for text in (profile.DESCRIPTION, profile.SHORT_DESCRIPTION):
            assert "модератор" not in text.lower(), text
        for command in profile.PRIVATE_COMMANDS + profile.GROUP_COMMANDS:
            assert "модератор" not in command.description.lower(), command.command

    def test_text_is_plain_language(self) -> None:
        """«Přijímačky» is what students call it; the bot names it properly."""
        for text in (profile.NAME, profile.DESCRIPTION, profile.SHORT_DESCRIPTION):
            assert slang(text) == [], text
        for command in profile.PRIVATE_COMMANDS + profile.GROUP_COMMANDS:
            assert slang(command.description) == [], command.command


class TestDefaultAdministratorRights:
    async def test_a_new_group_is_asked_for_what_the_commands_use(self) -> None:
        """The rights Telegram suggests when somebody adds the bot as an administrator."""
        bot = _bot()

        await profile.publish_profile(bot)

        rights = bot.set_my_default_administrator_rights.await_args.kwargs["rights"]
        granted = {name for name, value in rights.model_dump().items() if value is True}
        refused = {name for name, value in rights.model_dump().items() if value is False}
        # Everything an administrator of a group can hold, except the two that
        # do harm in the wrong hands: anonymity, and appointing administrators,
        # which would let a leaked token hand anybody the chat.
        assert refused == {"is_anonymous", "can_promote_members"}
        assert {"can_delete_messages", "can_restrict_members", "can_invite_users", "can_pin_messages"} <= granted
        assert {"can_change_info", "can_manage_topics", "can_manage_video_chats"} <= granted


class TestOneRefusalDoesNotStopTheRest:
    async def test_a_refused_rename_still_writes_the_menu(self) -> None:
        bot = _bot(name="old")
        bot.set_my_name.side_effect = RuntimeError("Flood control exceeded")

        await profile.publish_profile(bot)

        assert bot.set_my_commands.await_count == 2
        bot.set_my_default_administrator_rights.assert_awaited_once()

    async def test_a_refused_menu_still_writes_the_rest(self) -> None:
        bot = _bot(description="old")
        bot.set_my_commands.side_effect = RuntimeError("Telegram said no")

        await profile.publish_profile(bot)

        bot.set_my_description.assert_awaited_once()
        bot.set_my_default_administrator_rights.assert_awaited_once()

    async def test_narrower_menus_are_cleared(self) -> None:
        """Set by hand, one would win over ours without anybody noticing."""
        bot = _bot()

        await profile.publish_profile(bot)

        assert bot.delete_my_commands.await_count == 2


class TestStartupIsNotHeldHostage:
    async def test_a_failed_profile_does_not_stop_the_bot(self, monkeypatch) -> None:
        from app.presentation.telegram import bot as bot_module

        monkeypatch.setattr(bot_module, "publish_profile", AsyncMock(side_effect=RuntimeError("Telegram said no")))
        bot = AsyncMock()

        await bot_module.on_startup(bot)

        bot.delete_webhook.assert_awaited()
