"""The bot process lives exactly as long as its poller.

Everything else in the process (the MCP plane, the expiry sweep, the snapshot
loop) runs forever, so a process that waited for all of them outlived a poller
that had died at startup: alive, healthy-looking, deaf, and immune to SIGTERM.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.presentation.telegram import bot as bot_module
from app.presentation.telegram import moved

pytestmark = pytest.mark.asyncio


@pytest.fixture
def services(monkeypatch) -> list[str]:
    """Wire main() with fakes; returns the names of services that were cancelled."""
    cancelled: list[str] = []

    def forever(name: str):
        async def run(*_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

        return run

    main_bot = AsyncMock()
    main_bot.me.return_value = SimpleNamespace(username="konnekt_moder_bot")
    monkeypatch.setattr(bot_module, "_setup_main_bot", lambda _: (main_bot, AsyncMock()))
    monkeypatch.setattr(bot_module, "setup_container", lambda *_: None)
    monkeypatch.setattr(moved, "build_moved_bot", lambda: None)
    monkeypatch.setattr("app.mcp.runner.run_mcp_server", forever("mcp"))
    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", forever("sweep"))
    monkeypatch.setattr("app.chats.snapshots.run_snapshot_loop", forever("snapshots"))
    return cancelled


async def test_a_poller_that_dies_takes_the_process_down(monkeypatch, services) -> None:
    """A failed delete_webhook at boot must end in a restart, not a deaf bot."""

    async def failing_polling(*_args, **_kwargs):
        raise ConnectionError("network blip at startup")

    monkeypatch.setattr(bot_module.Dispatcher, "start_polling", failing_polling)
    main_bot = AsyncMock()
    main_bot.me.return_value = SimpleNamespace(username="konnekt_moder_bot")
    dp = bot_module.Dispatcher()
    monkeypatch.setattr(bot_module, "_setup_main_bot", lambda _: (main_bot, dp))

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(bot_module.main(), timeout=5)

    assert sorted(services) == ["mcp", "snapshots", "sweep"]


async def test_sigterm_ends_the_process_without_waiting_for_a_kill(monkeypatch, services) -> None:
    """Polling returns on SIGTERM; the services beside it must not hold the process."""

    async def stopped_polling(*_args, **_kwargs):
        return None

    monkeypatch.setattr(bot_module, "_run_polling", stopped_polling)

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert sorted(services) == ["mcp", "snapshots", "sweep"]


async def test_a_service_that_finishes_early_does_not_stop_the_bot(monkeypatch, services) -> None:
    """run_mcp_server returns at once when the plane is off; that is not a shutdown."""
    polling_done = asyncio.Event()

    async def idle(*_args, **_kwargs):
        return None

    async def polling(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        polling_done.set()

    monkeypatch.setattr("app.mcp.runner.run_mcp_server", idle)
    monkeypatch.setattr(bot_module, "_run_polling", polling)

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert polling_done.is_set()


async def test_a_service_that_crashes_takes_the_process_down(monkeypatch, services) -> None:
    async def crashing(*_args, **_kwargs):
        raise RuntimeError("sweep broke")

    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", crashing)
    monkeypatch.setattr(bot_module, "_run_polling", lambda *_a, **_k: asyncio.Event().wait())

    with pytest.raises(RuntimeError, match="sweep broke"):
        await asyncio.wait_for(bot_module.main(), timeout=5)


async def test_shutdown_closes_the_database_even_if_telegram_does_not_answer(monkeypatch) -> None:
    """`bot.close()` is the Bot API's server-move call, not a session close."""
    close_db = AsyncMock()
    monkeypatch.setattr(bot_module, "close_db", close_db)
    bot = AsyncMock()
    bot.delete_webhook.side_effect = ConnectionError("gone")

    await bot_module.on_shutdown(bot)

    bot.close.assert_not_awaited()
    close_db.assert_awaited_once()
