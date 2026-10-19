"""The retired catalog bot answers with where Konnekt went.

@student_cz_bot was the catalog's own bot until everything moved into this one.
People still write to it; it used to say nothing at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardMarkup
from app.presentation.telegram import moved

pytestmark = pytest.mark.unit


async def test_a_private_message_gets_the_new_address() -> None:
    message = AsyncMock()

    await moved.point_to_konnekt(message, konnekt_username="konnekt_moder_bot")

    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert "@konnekt_moder_bot" in text
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][0].url == "https://t.me/konnekt_moder_bot"


def test_only_private_chats_are_answered() -> None:
    router = moved.build_router()
    filters = router.message.handlers[0].filters
    assert filters
    check = filters[0].callback

    assert check(SimpleNamespace(chat=SimpleNamespace(type="private")))
    assert not check(SimpleNamespace(chat=SimpleNamespace(type="supergroup")))


def test_without_a_token_there_is_no_moved_bot(monkeypatch) -> None:
    monkeypatch.setattr(moved.settings.telegram, "retired_token", "")

    assert moved.build_moved_bot() is None


async def test_the_retired_bot_leaves_the_signals_to_the_main_bot(monkeypatch) -> None:
    from app.presentation.telegram import bot as bot_module

    calls: list[dict] = []

    async def fake_run_polling(bot, dp, *, name, **kwargs):
        calls.append({"name": name, **kwargs})

    main_bot = AsyncMock()
    main_bot.me.return_value = SimpleNamespace(username="konnekt_moder_bot")
    monkeypatch.setattr(bot_module, "_setup_main_bot", lambda _: (main_bot, AsyncMock()))
    monkeypatch.setattr(bot_module, "setup_container", lambda *_: None)
    monkeypatch.setattr(bot_module, "_run_polling", fake_run_polling)
    monkeypatch.setattr(moved, "build_moved_bot", lambda: (AsyncMock(), AsyncMock()))

    async def idle(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.mcp.runner.run_mcp_server", idle)
    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", idle)
    monkeypatch.setattr("app.chats.snapshots.run_snapshot_loop", idle)

    await bot_module.main()

    retired = next(c for c in calls if c["name"] == "moved")
    assert retired["handle_signals"] is False
    assert retired["konnekt_username"] == "konnekt_moder_bot"
    assert "handle_signals" not in next(c for c in calls if c["name"] == "main")
