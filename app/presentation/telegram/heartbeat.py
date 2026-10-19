"""The poller's pulse, for the healthcheck and for the process itself.

A live process said nothing about whether the bot still heard anyone: the old
healthcheck matched its own shell, and a poller that stalled left everything
around it running. Every answered getUpdates touches a file, and long polling
answers within seconds even when nobody writes, so a stale file means a deaf
bot. The container reports it as unhealthy, and the watchdog ends the process
so the container restarts.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import GetUpdates

from app.core.logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.client.session.middlewares.base import NextRequestMiddlewareType
    from aiogram.methods import TelegramMethod

logger = get_logger("bot.heartbeat")

# Read by the bot's healthcheck in docker-compose.yaml.
HEARTBEAT = Path("/tmp/bot-heartbeat")  # noqa: S108 — container-local, nothing reads it but the check


class PollingStalledError(RuntimeError):
    """getUpdates has not answered for longer than polling ever takes."""


class PollingHeartbeat(BaseRequestMiddleware):
    """Touch the heartbeat after every getUpdates that Telegram answered."""

    def __init__(self, path: Path = HEARTBEAT) -> None:
        self.path = path

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[Any],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        response = await make_request(bot, method)
        if isinstance(method, GetUpdates):
            self.path.touch()
        return response


async def watch(
    path: Path = HEARTBEAT,
    *,
    max_age_seconds: float = 300,
    interval_seconds: float = 30,
    grace_seconds: float = 300,
) -> None:
    """Raise once the heartbeat is older than any poll could explain.

    Before the first answered poll there is no file; startup gets the grace
    period to produce one.
    """
    started = time.monotonic()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            if time.monotonic() - started < grace_seconds:
                continue
            age = time.monotonic() - started
        if age > max_age_seconds:
            logger.error("polling_stalled", seconds_since_last_poll=round(age))
            raise PollingStalledError(f"no getUpdates answered for {round(age)}s")
