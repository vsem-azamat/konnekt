"""The retired bots answer with where Konnekt went.

@student_cz_bot was the catalog's own bot until everything moved into this one,
and @konnekt_moder_bot was this one until it moved to a new address. People
still write to both; without this they would hear nothing at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardMarkup
from app.core.config import TelegramSettings
from app.presentation.telegram import moved

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
        # Pasting the current token among the retired ones would put a second
        # poller on the main bot and steal moderation's updates.
        (f"{MAIN},{STUDENT}", [STUDENT]),
    ],
)
def test_retired_tokens_are_read_however_they_were_written(monkeypatch, raw: str | None, expected: list[str]) -> None:
    assert _retired(monkeypatch, raw) == expected


def test_without_a_token_there_is_no_moved_bot(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [])

    assert moved.build_moved_bots() == []


def test_every_retired_token_gets_a_bot_and_a_dispatcher_of_its_own(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [STUDENT, MODER])

    built = moved.build_moved_bots()

    assert [bot.token for bot, _ in built] == [STUDENT, MODER]
    # A dispatcher polls one bot at a time; sharing one would start only the first.
    assert built[0][1] is not built[1][1]


def test_a_malformed_token_is_skipped_rather_than_taking_moderation_down(monkeypatch) -> None:
    """`Bot()` checks the token as it is built, before anything is contained."""
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", ["not-a-token", MODER])

    assert [bot.token for bot, _ in moved.build_moved_bots()] == [MODER]


async def test_a_retired_bot_stops_offering_the_mini_app_and_the_commands() -> None:
    """Telegram keeps both on the bot after it is retired.

    The old Mini App button signs in with the old token, which the API no
    longer accepts, and the old commands lead nowhere: neither would ever
    reach the message saying where Konnekt went.
    """
    from aiogram.types import MenuButtonCommands

    bot = AsyncMock()

    await moved.retire_profile(bot)

    assert isinstance(bot.set_chat_menu_button.await_args.kwargs["menu_button"], MenuButtonCommands)
    scopes = {type(call.kwargs.get("scope")).__name__ for call in bot.delete_my_commands.await_args_list}
    assert {"BotCommandScopeDefault", "BotCommandScopeAllPrivateChats", "BotCommandScopeAllGroupChats"} <= scopes


async def test_the_profile_is_reset_when_a_retired_bot_starts(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_tokens", [MODER])
    ((_, dp),) = moved.build_moved_bots()

    assert [handler.callback for handler in dp.startup.handlers] == [moved.retire_profile]


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
    monkeypatch.setattr(moved, "build_moved_bots", lambda: retired)

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
