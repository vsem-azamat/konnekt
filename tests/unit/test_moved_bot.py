"""The retired bots answer with where Konnekt went.

@student_cz_bot was the catalog's own bot until everything moved into this one,
and @konnekt_moder_bot was this one until it moved to a new address. People
still write to both; without this they would hear nothing at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardMarkup
from app.core.config import TelegramSettings
from app.presentation.telegram import moved
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

MAIN = "100:main"
STUDENT = "200:student"
MODER = "300:moder"


async def test_a_private_message_gets_the_new_address() -> None:
    message = AsyncMock()

    await moved.point_to_konnekt(message, konnekt_username="konnekt_cz_bot")

    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert "@konnekt_cz_bot" in text
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][0].url == "https://t.me/konnekt_cz_bot"


def test_only_private_chats_are_answered() -> None:
    router = moved.build_router()
    filters = router.message.handlers[0].filters
    assert filters
    check = filters[0].callback

    assert check(SimpleNamespace(chat=SimpleNamespace(type="private")))
    assert not check(SimpleNamespace(chat=SimpleNamespace(type="supergroup")))


def _retired(monkeypatch, raw: str | None) -> list[str]:
    """Read the way a deployed process does: from the environment, no `.env`."""
    monkeypatch.setenv("MODERATOR_BOT_TOKEN", MAIN)
    if raw is None:
        monkeypatch.delenv("MODERATOR_BOT_RETIRED_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MODERATOR_BOT_RETIRED_TOKEN", raw)
    return TelegramSettings(_env_file=None).retired_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        # A secret that was never given a value arrives empty.
        ("", []),
        # One token: what is deployed today, and must keep working.
        (STUDENT, [STUDENT]),
        (f"{STUDENT},{MODER}", [STUDENT, MODER]),
        (f" {STUDENT} , {MODER} ,", [STUDENT, MODER]),
        # One per line is how a secret gets pasted; a token holds no whitespace.
        (f"{STUDENT}\n{MODER}\n", [STUDENT, MODER]),
        # Two pollers on one token fight over its updates and both lose.
        (f"{STUDENT},{STUDENT}", [STUDENT]),
    ],
)
def test_retired_tokens_are_read_however_they_were_written(monkeypatch, raw: str | None, expected: list[str]) -> None:
    assert _retired(monkeypatch, raw) == expected


def test_without_a_token_there_is_no_moved_bot(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [])

    assert moved.build_moved_bots(MagicMock()) == []


def test_every_retired_token_gets_a_bot_and_a_dispatcher_of_its_own(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [STUDENT, MODER])

    built = moved.build_moved_bots(MagicMock())

    assert [bot.token for bot, _ in built] == [STUDENT, MODER]
    # A dispatcher polls one bot at a time; sharing one would start only the first.
    assert built[0][1] is not built[1][1]


def _logged(monkeypatch) -> MagicMock:
    """The module's logger, replaced: what other tests did to logging must not decide these."""
    logger = MagicMock()
    monkeypatch.setattr(moved, "logger", logger)
    return logger


def test_a_malformed_token_is_skipped_rather_than_taking_moderation_down(monkeypatch) -> None:
    """`Bot()` checks the token as it is built, before anything is contained."""
    logger = _logged(monkeypatch)
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", ["123:with spaces", MODER])

    assert [bot.token for bot, _ in moved.build_moved_bots(MagicMock())] == [MODER]
    logger.error.assert_called_once_with("retired_token_malformed", position=1)
    assert "with spaces" not in str(logger.mock_calls)


def test_the_current_token_among_the_retired_is_skipped_with_a_warning(monkeypatch) -> None:
    """A second poller on the main bot would take turns with it for moderation's updates."""
    logger = _logged(monkeypatch)
    monkeypatch.setattr(moved.settings.telegram, "token", MAIN)
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [STUDENT, MAIN])

    assert [bot.token for bot, _ in moved.build_moved_bots(MagicMock())] == [STUDENT]
    logger.warning.assert_called_once_with("retired_token_is_current", position=2)
    assert MAIN not in str(logger.mock_calls)


ALL_SCOPES = {
    "BotCommandScopeDefault",
    "BotCommandScopeAllPrivateChats",
    "BotCommandScopeAllGroupChats",
    "BotCommandScopeAllChatAdministrators",
}


async def test_a_retired_bot_says_it_moved_and_drops_the_mini_app_and_the_commands() -> None:
    """Telegram keeps all of it on the bot after it is retired.

    The old Mini App button signs in with the old token, which the API no
    longer accepts, the old commands lead nowhere, and the old description
    still says to press a button that is gone.
    """
    from aiogram.types import MenuButtonCommands

    bot = AsyncMock()

    await moved.retire_profile(bot, konnekt_username="konnekt_cz_bot")

    assert isinstance(bot.set_chat_menu_button.await_args.kwargs["menu_button"], MenuButtonCommands)
    scopes = {
        type(call.kwargs["scope"]).__name__
        for call in bot.delete_my_commands.await_args_list
        if call.kwargs.get("language_code") is None
    }
    assert scopes == ALL_SCOPES
    description = bot.set_my_description.await_args_list[0].kwargs["description"]
    short = bot.set_my_short_description.await_args_list[0].kwargs["short_description"]
    assert "@konnekt_cz_bot" in description
    assert "@konnekt_cz_bot" in short
    # Telegram's limits.
    assert len(description) <= 512
    assert len(short) <= 120


async def test_a_retired_bot_is_retired_in_every_language() -> None:
    """Telegram shows a language's own text before the default one.

    The live bot writes ru/uk/cs/en; left alone on a retired bot, they would
    keep its old description and menu in front of almost everybody.
    """
    from app.presentation.telegram import profile

    bot = AsyncMock()

    await moved.retire_profile(bot, konnekt_username="konnekt_cz_bot")

    for language in profile.LANGUAGES:
        scopes = {
            type(call.kwargs["scope"]).__name__
            for call in bot.delete_my_commands.await_args_list
            if call.kwargs.get("language_code") == language
        }
        assert scopes == ALL_SCOPES, language
        assert call_for(bot.set_my_description, language).kwargs["description"] == ""
        assert call_for(bot.set_my_short_description, language).kwargs["short_description"] == ""


def call_for(method: AsyncMock, language: str):
    (call,) = [c for c in method.await_args_list if c.kwargs.get("language_code") == language]
    return call


async def test_one_failed_reset_step_leaves_the_others_done() -> None:
    bot = AsyncMock()
    bot.set_chat_menu_button.side_effect = RuntimeError("flood control")

    await moved.retire_profile(bot, konnekt_username="konnekt_cz_bot")

    assert {type(call.kwargs["scope"]).__name__ for call in bot.delete_my_commands.await_args_list} == ALL_SCOPES
    bot.set_my_description.assert_awaited()
    bot.set_my_short_description.assert_awaited()


async def test_a_failed_step_is_named_as_telegram_names_the_scope() -> None:
    bot = AsyncMock()
    bot.delete_my_commands.side_effect = RuntimeError("flood control")

    with capture_logs() as logs:
        await moved.retire_profile(bot, konnekt_username="konnekt_cz_bot")

    steps = {log["step"] for log in logs if log["event"] == "retired_profile_step_failed"}
    assert "commands:all_group_chats" in steps
    assert "commands:default:uk" in steps


async def test_the_profile_is_reset_when_a_retired_bot_starts(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [MODER])
    ((_, dp),) = moved.build_moved_bots(MagicMock())

    assert [handler.callback for handler in dp.startup.handlers] == [moved.retire_profile]


async def test_a_retired_bot_starts_with_the_new_address_to_hand(monkeypatch) -> None:
    """The startup handler gets the new username from the polling call, as the message handler does."""
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [MODER])
    ((_, dp),) = moved.build_moved_bots(MagicMock())
    bot = AsyncMock()

    await dp.emit_startup(bot=bot, konnekt_username="konnekt_cz_bot")

    assert "@konnekt_cz_bot" in bot.set_my_description.await_args_list[0].kwargs["description"]


async def test_every_retired_bot_leaves_the_signals_to_the_main_bot(monkeypatch) -> None:
    from app.presentation.telegram import bot as bot_module

    calls: list[dict] = []

    async def fake_run_polling(bot, dp, *, name, **kwargs):
        calls.append({"name": name, **kwargs})

    main_bot = AsyncMock()
    main_bot.me.return_value = SimpleNamespace(username="konnekt_cz_bot")
    monkeypatch.setattr(bot_module, "_setup_main_bot", lambda _: (main_bot, AsyncMock()))
    monkeypatch.setattr(bot_module, "setup_container", lambda *_: None)
    monkeypatch.setattr(bot_module, "_run_polling", fake_run_polling)
    retired = [(SimpleNamespace(id=200), AsyncMock()), (SimpleNamespace(id=300), AsyncMock())]
    monkeypatch.setattr(moved, "build_moved_bots", lambda _sm: retired)

    async def idle(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.mcp.runner.run_mcp_server", idle)
    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", idle)
    monkeypatch.setattr("app.chats.snapshots.run_snapshot_loop", idle)

    await bot_module.main()

    moved_calls = [c for c in calls if c["name"] != "main"]
    assert sorted(c["name"] for c in moved_calls) == ["moved:200", "moved:300"]
    for call in moved_calls:
        assert call["handle_signals"] is False
        assert call["konnekt_username"] == "konnekt_cz_bot"
    assert "handle_signals" not in next(c for c in calls if c["name"] == "main")


async def test_a_visit_to_a_retired_bot_is_kept_but_never_counts_as_a_way_to_reach_anyone(
    monkeypatch, session_maker
) -> None:
    import datetime

    from aiogram.types import Chat, Message, Update, User
    from app.core.enums import Touchpoint
    from app.db.models import AudienceReach, AudienceTouch
    from sqlalchemy import select

    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [MODER])
    ((_, dp),) = moved.build_moved_bots(session_maker)
    person = User(id=31, is_bot=False, first_name="Old")
    message = Message(
        message_id=1,
        date=datetime.datetime.now(datetime.UTC),
        chat=Chat(id=31, type="private"),
        from_user=person,
        text="hi",
    )
    bot = AsyncMock()

    await dp.feed_update(bot, Update(update_id=1, message=message), konnekt_username="konnekt_cz_bot")

    async with session_maker() as session:
        touches = [(t.user_id, t.touchpoint) for t in await session.scalars(select(AudienceTouch))]
        reach = list(await session.scalars(select(AudienceReach)))
    assert touches == [(31, Touchpoint.MOVED_BOT)]
    assert reach == []
