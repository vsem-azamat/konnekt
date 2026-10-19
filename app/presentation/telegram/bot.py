"""Main entry point — the moderator bot and the services beside it.

One Telegram identity, one dispatcher. Alongside its polling loop this process
serves the MCP control plane, sweeps expired pending actions and records member
counts — all of which need a long-lived bot, which is what this process is.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import MenuButton, MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from app.core.alerts import AlertHandler
from app.core.config import settings
from app.core.container import setup_container
from app.core.logging import get_logger, setup_logging

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.db.session import close_db, get_session_maker
from app.presentation.telegram import heartbeat
from app.presentation.telegram.handlers import router
from app.presentation.telegram.middlewares import (
    ApprovedChatGateMiddleware,
    BlacklistMiddleware,
    DependenciesMiddleware,
    HistoryMiddleware,
    ManagedChatsMiddleware,
)
from app.presentation.telegram.profile import publish_profile

setup_logging()
logger = get_logger("bot")


# ---------------------------------------------------------------------------
# Lifecycle callbacks (main bot only)
# ---------------------------------------------------------------------------


async def _publish_menu_button(bot: Bot) -> None:
    """Put the catalogue on the chat menu, one tap from any private chat.

    Telegram stores this on the bot rather than on a message, so it is set once
    here and survives every restart — which is also why the plain-http and
    unconfigured cases must reset it instead of doing nothing. A deployment
    that turns the public site off would otherwise keep offering a button to an
    address that no longer answers, set by a deployment that is long gone.
    """
    url = settings.webapi.public_url.rstrip("/")

    # https is Telegram's requirement for a Mini App, not ours; local
    # development runs over http and gets the ordinary command menu.
    if url.startswith("https://"):
        button: MenuButton = MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=url))
    else:
        button = MenuButtonCommands()

    await bot.set_chat_menu_button(menu_button=button)


async def on_startup(bot: Bot) -> None:
    """Main bot startup: clear any leftover webhook before polling."""
    try:
        await bot.delete_webhook()
        logger.info("main_bot_startup_complete")
    except Exception as e:
        logger.error("startup_error", error=str(e), exc_info=True)
        raise

    # Deliberately not fatal, and deliberately after the line above: a bot that
    # could not draw its menu button still moderates, and refusing to start
    # over a cosmetic call would trade the whole service for a nicety.
    try:
        await _publish_menu_button(bot)
    except Exception as e:
        logger.warning("menu_button_not_set", error=str(e))
    try:
        await publish_profile(bot)
    except Exception as e:
        logger.warning("profile_not_set", error=str(e))


async def on_shutdown(bot: Bot) -> None:
    """Main bot shutdown.

    Not `bot.close()`: that is the Bot API method for moving a bot between API
    servers, refused for ten minutes after launch. The HTTP session is closed
    by `_run_polling`, and the database by `main` once nothing uses it.
    """
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.warning("shutdown_delete_webhook_failed", error=str(e))
    logger.info("main_bot_shutdown_complete")


# ---------------------------------------------------------------------------
# Initialization helpers
# ---------------------------------------------------------------------------


def _setup_main_bot(session_maker: async_sessionmaker[AsyncSession]) -> tuple[Bot, Dispatcher]:
    """Create and configure the moderation bot — the only bot in this process."""
    bot = Bot(token=settings.telegram.token, default=DefaultBotProperties(parse_mode="HTML"))
    bot.session.middleware(heartbeat.PollingHeartbeat())
    return bot, build_dispatcher(bot, session_maker)


def build_dispatcher(bot: Bot, session_maker: async_sessionmaker[AsyncSession]) -> Dispatcher:
    """The moderator dispatcher, middlewares in their order, for any bot."""
    dp = Dispatcher()

    dp.update.middleware(DependenciesMiddleware(session_pool=session_maker, bot=bot))
    dp.update.middleware(ManagedChatsMiddleware())
    dp.update.middleware(HistoryMiddleware())
    dp.update.middleware(ApprovedChatGateMiddleware())
    # Outer, so they see every message and membership change: an inner
    # middleware runs only once a handler's filters match, and plain text
    # matches none, so a blacklisted member could write freely. Also at the
    # door: a blacklisted user who rejoins must not get to speak once first.
    dp.message.outer_middleware(BlacklistMiddleware())
    dp.chat_member.outer_middleware(BlacklistMiddleware())
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    dp.include_router(router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


async def _run_polling(bot: Bot, dp: Dispatcher, *, name: str, **kwargs: Any) -> None:
    """Run a single bot's polling loop with structured logging."""
    logger.info("polling_start", bot=name)
    try:
        await dp.start_polling(bot, **kwargs)
    except asyncio.CancelledError:
        logger.info("polling_cancelled", bot=name)
        raise
    except Exception:
        # Raised on, not swallowed: a poller that died must end the process
        # so the container restarts, rather than leave it running deaf.
        logger.exception("polling_error", bot=name)
        raise
    finally:
        await bot.session.close()
        logger.info("polling_stopped", bot=name)


async def main() -> None:
    """Application entry point."""
    logger.info("starting", environment=settings.environment)

    # First, so that a failure anywhere in the process reaches the report chat.
    close_alerts = await _start_alerts()
    try:
        await _serve()
    finally:
        await close_alerts()
        logger.info("stopped")


async def _serve() -> None:
    """The bot, its poller and the services beside it, until the poller ends."""
    session_maker = get_session_maker()

    main_bot, main_dp = _setup_main_bot(session_maker)
    setup_container(session_maker, main_bot)

    tasks: list[Coroutine[Any, Any, None]] = []

    from app.presentation.telegram.moved import build_moved_bot

    if moved := build_moved_bot():
        moved_bot, moved_dp = moved
        konnekt_username = (await main_bot.me()).username
        tasks.append(
            # Contained: a revoked retired token must not crash-loop moderation.
            _contained(
                # The main bot owns SIGTERM: aiogram replaces the handler on each start_polling,
                # and taking it here would leave the main bot without a shutdown path.
                _run_polling(
                    moved_bot,
                    moved_dp,
                    name="moved",
                    handle_signals=False,
                    allowed_updates=["message"],
                    konnekt_username=konnekt_username,
                ),
                name="moved",
            )
        )

    # The MCP control plane runs here, not in the web API: its proposals send
    # confirmation buttons, and Telegram answers a press to the identity that
    # sent it, which is this process's bot. Returns at once when MCP is off.
    from app.mcp.runner import run_mcp_server
    from app.moderation.pending_actions import run_expiry_sweep

    tasks.append(run_mcp_server())
    tasks.append(run_expiry_sweep(session_maker))

    # What people wrote is kept half a year (#174).
    from app.moderation.history_service import run_history_retention

    tasks.append(run_history_retention(session_maker))

    # Member counts are recorded here because this is the process holding a
    # long-lived bot. Nothing about it is conditional any more: the loop asks
    # Telegram over the bot token, which every deployment has by definition.
    from app.chats.snapshots import run_snapshot_loop

    tasks.append(run_snapshot_loop(session_maker=session_maker, bot=main_bot))

    # A stalled poller ends the process, so the container restarts it.
    tasks.append(heartbeat.watch())

    polling = _run_polling(
        main_bot,
        main_dp,
        name="main",
        # Edits too: a message posted clean and edited into an ad went unseen.
        allowed_updates=["message", "edited_message", "callback_query", "chat_member", "chat_join_request"],
    )
    try:
        await _supervise(polling, tasks)
    finally:
        try:
            await close_db()
        except Exception as e:
            logger.error("close_db_failed", error=str(e), exc_info=True)


async def _start_alerts() -> Callable[[], Awaitable[None]]:
    """Send this process's errors to the report chat, until the returned closer runs.

    Outside the supervised tasks and on a session of its own: the alert that
    matters most is the one logged as the poller dies, and by then the
    services are being cancelled and the main bot's session closed.
    """
    alert_bot = Bot(token=settings.telegram.token)
    report_chat = settings.admin.default_report_chat_id
    handler = AlertHandler(process="bot")
    handler.start(lambda text: alert_bot.send_message(report_chat, text, parse_mode=None))

    async def close() -> None:
        await handler.stop()
        await alert_bot.session.close()

    return close


async def _contained(service: Coroutine[Any, Any, None], *, name: str) -> None:
    """Run a service whose failure should be logged rather than end the process."""
    try:
        await service
    except Exception:
        logger.exception("service_failed", service=name)


async def _supervise(polling: Coroutine[Any, Any, None], services: list[Coroutine[Any, Any, None]]) -> None:
    """Run the services for as long as the main poller runs, and no longer.

    The poller ending, by SIGTERM or by failing, ends the process: waiting for
    every task kept it alive after a failed start, deaf and immune to SIGTERM,
    and made every deploy end in a kill. A service that returns is simply done
    (the MCP plane returns at once when it is off); one that raises takes the
    process down with it, so a restart brings it back.
    """
    main = asyncio.ensure_future(polling)
    running = {asyncio.ensure_future(service) for service in services}
    try:
        while True:
            done, running = await asyncio.wait({main, *running}, return_when=asyncio.FIRST_COMPLETED)
            running.discard(main)
            if main in done:
                main.result()
                return
            for task in done:
                task.result()
    finally:
        for task in (main, *running):
            task.cancel()
        await asyncio.gather(main, *running, return_exceptions=True)


def run_bot() -> None:
    """Run the bot."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("stopped_by_user")
    except Exception as e:
        logger.error("unexpected_error", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    run_bot()
