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

    async def no_alerts():
        async def close() -> None:
            return None

        return close

    monkeypatch.setattr(bot_module, "_start_alerts", no_alerts)
    monkeypatch.setattr("app.mcp.runner.run_mcp_server", forever("mcp"))
    monkeypatch.setattr("app.moderation.pending_actions.run_expiry_sweep", forever("sweep"))
    monkeypatch.setattr("app.chats.snapshots.run_snapshot_loop", forever("snapshots"))
    monkeypatch.setattr("app.moderation.history_service.run_history_retention", forever("retention"))
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

    assert sorted(services) == ["mcp", "retention", "snapshots", "sweep"]


async def test_sigterm_ends_the_process_without_waiting_for_a_kill(monkeypatch, services) -> None:
    """Polling returns on SIGTERM; the services beside it must not hold the process."""

    async def stopped_polling(*_args, **_kwargs):
        return None

    monkeypatch.setattr(bot_module, "_run_polling", stopped_polling)

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert sorted(services) == ["mcp", "retention", "snapshots", "sweep"]


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


async def test_shutdown_does_not_call_the_bot_api_close(monkeypatch) -> None:
    """`bot.close()` is the Bot API's server-move call, not a session close."""
    bot = AsyncMock()
    bot.delete_webhook.side_effect = ConnectionError("gone")

    await bot_module.on_shutdown(bot)

    bot.close.assert_not_awaited()


async def test_the_database_closes_after_everything_that_uses_it(monkeypatch, services) -> None:
    """Closed in on_shutdown, it went before the sweep and the snapshot loop stopped."""
    order: list[str] = []

    async def close_db() -> None:
        order.append(f"db after {sorted(services)}")

    async def stopped_polling(*_args, **_kwargs):
        return None

    monkeypatch.setattr(bot_module, "close_db", close_db)
    monkeypatch.setattr(bot_module, "_run_polling", stopped_polling)

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert order == ["db after ['mcp', 'retention', 'snapshots', 'sweep']"]


async def test_the_retired_bot_failing_does_not_take_moderation_down(monkeypatch, services) -> None:
    """A revoked retired token must not crash-loop the moderator bot."""
    main_ran = asyncio.Event()

    async def polling(_bot, _dp, *, name, **_kwargs):
        if name == "moved":
            raise ConnectionError("retired token revoked")
        await asyncio.sleep(0.05)
        main_ran.set()

    monkeypatch.setattr(bot_module, "_run_polling", polling)
    monkeypatch.setattr(moved, "build_moved_bot", lambda: (AsyncMock(), AsyncMock()))

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert main_ran.is_set()


async def test_a_failure_before_polling_starts_still_reaches_the_alerts(monkeypatch, services) -> None:
    stopped: list[str] = []

    async def alerts():
        async def close() -> None:
            stopped.append("alerts")

        return close

    def broken_setup(_):
        raise RuntimeError("bad token")

    monkeypatch.setattr(bot_module, "_start_alerts", alerts)
    monkeypatch.setattr(bot_module, "_setup_main_bot", broken_setup)

    with pytest.raises(RuntimeError, match="bad token"):
        await bot_module.main()

    assert stopped == ["alerts"]


async def test_polling_asks_for_edits(monkeypatch, services) -> None:
    """Without edited_message, a message edited into an ad was never seen."""
    polled: dict = {}

    async def polling(_bot, _dp, *, name, **kwargs):
        polled.update(kwargs)

    monkeypatch.setattr(bot_module, "_run_polling", polling)

    await asyncio.wait_for(bot_module.main(), timeout=5)

    assert "edited_message" in polled["allowed_updates"]
