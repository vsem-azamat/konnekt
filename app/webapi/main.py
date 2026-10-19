"""FastAPI app factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.alerts import AlertHandler
from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.routes import (
    admin,
    auth,
    chats,
    health,
    join_check,
    public,
    spam,
    stats,
    users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = get_logger("webapi.main")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Start what this process can actually run.

    Not the snapshot loop. It lived here and never once ran: the container it
    asks for a Telethon client is a per-process singleton wired by the bot's
    startup, and the account's session file is mounted into the bot container
    alone. Reading member counts belongs beside the session; this process reads
    the rows that produces.
    """
    from app.webapi.services.publish_bot import build_publish_bot, close_publish_bot

    _app.state.publish_bot = build_publish_bot()
    logger.info("publish_bot_started")
    bot = _app.state.publish_bot
    report_chat = settings.admin.default_report_chat_id
    alerts = asyncio.create_task(
        AlertHandler(process="webapi").run(lambda text: bot.send_message(report_chat, text, parse_mode=None))
    )
    try:
        yield
    finally:
        alerts.cancel()
        await asyncio.gather(alerts, return_exceptions=True)
        await close_publish_bot(_app.state.publish_bot)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Moderator Bot Admin API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.webapi.allowed_origins or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(public.router, prefix="/api")
    app.include_router(join_check.router, prefix="/api")
    app.include_router(chats.router, prefix="/api")
    app.include_router(spam.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    # Default no-op singleton for test environments (ASGITransport bypasses
    # lifespan). _lifespan replaces this with the real instance at startup.
    app.state.publish_bot = None  # _lifespan replaces with real Bot at startup

    return app


app = create_app()
