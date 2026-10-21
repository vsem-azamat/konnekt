"""What the bot tells Prometheus.

Updates by kind and outcome, Bot API calls by method, the age of the poller's
pulse and the depth of the queues. Series are never per chat or person
(app/core/metrics.py says why). The bot has no web front, so it serves the
scrape itself, on a port of its own: not the MCP plane's, which must stay
unreachable from outside.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select
from starlette.responses import PlainTextResponse, Response

from app.core import metrics
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import JoinCaptcha, PendingAction
from app.presentation.telegram.heartbeat import HEARTBEAT

if TYPE_CHECKING:
    from collections.abc import Generator

    from aiogram import Bot
    from aiogram.client.session.middlewares.base import NextRequestMiddlewareType
    from aiogram.methods import TelegramMethod
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from starlette.types import Receive, Scope, Send

logger = get_logger("bot.metrics")

UPDATES = Counter("bot_updates_total", "Updates handled", ["update_type", "outcome"])
UPDATE_DURATION = Histogram(
    "bot_update_duration_seconds",
    "Time to handle one update",
    ["update_type"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
API_CALLS = Counter("bot_telegram_api_calls_total", "Bot API calls", ["method", "outcome"])
API_DURATION = Histogram(
    "bot_telegram_api_duration_seconds",
    "Bot API call time",
    ["method"],
    # getUpdates is a long poll of about ten seconds; the rest are quick.
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 30),
)
HEARTBEAT_AGE = Gauge("bot_polling_heartbeat_age_seconds", "Seconds since a getUpdates was answered")
QUEUE_DEPTH = Gauge("bot_queue_depth", "Work waiting on a person or a timer", ["queue"])


def heartbeat_age() -> float:
    """NaN until the first poll has been answered: no pulse yet is not a stalled one."""
    try:
        return max(0.0, time.time() - HEARTBEAT.stat().st_mtime)
    except FileNotFoundError:
        return float("nan")


HEARTBEAT_AGE.set_function(lambda: heartbeat_age())


class ApiCallMetrics(BaseRequestMiddleware):
    """Count and time every Bot API call; a failure is labelled by its class."""

    async def __call__(
        self, make_request: NextRequestMiddlewareType[Any], bot: Bot, method: TelegramMethod[Any]
    ) -> Any:
        name = method.__api_method__
        started = time.perf_counter()
        outcome = "ok"
        try:
            return await make_request(bot, method)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as err:
            outcome = type(err).__name__
            raise
        finally:
            API_CALLS.labels(method=name, outcome=outcome).inc()
            API_DURATION.labels(method=name).observe(time.perf_counter() - started)


async def refresh_queue_depths(session: AsyncSession) -> None:
    """One read of what is waiting: captchas for an answer or a decision, proposals for a press."""
    captchas = dict(
        (await session.execute(select(JoinCaptcha.status, func.count()).group_by(JoinCaptcha.status))).tuples().all()
    )
    QUEUE_DEPTH.labels(queue="captcha_pending").set(captchas.get(JoinCaptcha.STATUS_PENDING, 0))
    QUEUE_DEPTH.labels(queue="captcha_held").set(captchas.get(JoinCaptcha.STATUS_HELD, 0))
    pending = await session.scalar(
        select(func.count()).select_from(PendingAction).where(PendingAction.status == "pending")
    )
    QUEUE_DEPTH.labels(queue="pending_actions").set(pending or 0)


async def run_queue_depths(session_maker: async_sessionmaker[AsyncSession], interval_seconds: int = 30) -> None:
    """Keep the queue gauges current for as long as the bot runs; nothing to do while nobody scrapes."""
    if not metrics.enabled():
        return
    while True:
        try:
            async with session_maker() as session:
                await refresh_queue_depths(session)
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("queue_depths_failed")
            await asyncio.sleep(interval_seconds)


def build_metrics_app() -> Any:
    """The scrape and nothing else: `GET /metrics`, behind the bearer token."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        response: Response
        if scope["path"] != "/metrics" or not metrics.enabled():
            response = PlainTextResponse("not found", status_code=404)
        elif scope["method"] != "GET":
            response = PlainTextResponse("method not allowed", status_code=405)
        elif not metrics.authorized(dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")):
            response = PlainTextResponse("unauthorized", status_code=401)
        else:
            body, content_type = metrics.render()
            response = Response(body, media_type=content_type)
        await response(scope, receive, send)

    return app


async def run_metrics_server() -> None:
    """Serve the scrape until cancelled; returns at once while no secret is set."""
    if not metrics.enabled():
        logger.info("metrics_disabled")
        return
    import uvicorn

    class _BotOwnsSignals(uvicorn.Server):
        # aiogram replaces the signal handlers on each start_polling; the main
        # bot owns SIGTERM, as for the MCP plane.
        @contextlib.contextmanager
        def capture_signals(self) -> Generator[None, None, None]:
            yield

    server = _BotOwnsSignals(
        uvicorn.Config(
            build_metrics_app(),
            host=settings.observability.metrics_host,
            port=settings.observability.metrics_port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    logger.info("metrics_serving", port=settings.observability.metrics_port)
    try:
        await server.serve()
    finally:
        logger.info("metrics_stopped")
