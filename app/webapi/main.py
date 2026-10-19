"""FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.alerts import AlertHandler
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.webapi.deps import require_super_admin
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

# Without it structlog prints to stdout and nothing reaches the root logger:
# no JSON in production, no LOG_FILE_PATH, and no error alerts.
setup_logging()
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
    alerts = AlertHandler(process="webapi")
    alerts.start(lambda text: bot.send_message(report_chat, text, parse_mode=None))
    try:
        yield
    finally:
        await alerts.stop()
        await close_publish_bot(_app.state.publish_bot)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Moderator Bot Admin API",
        version="0.1.0",
        # Not in production: /api/* is public through the edge, and the schema
        # is a map of every console route for whoever asks.
        docs_url=None if settings.environment == "production" else "/api/docs",
        openapi_url=None if settings.environment == "production" else "/api/openapi.json",
        redoc_url=None,
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
    # The console, guarded at the router: a route added here cannot forget to
    # ask, and the question comes before anything else a route depends on.
    console = [Depends(require_super_admin)]
    app.include_router(chats.router, prefix="/api", dependencies=console)
    app.include_router(spam.router, prefix="/api", dependencies=console)
    app.include_router(stats.router, prefix="/api", dependencies=console)
    app.include_router(users.router, prefix="/api", dependencies=console)
    app.include_router(admin.router, prefix="/api", dependencies=console)

    # Default no-op singleton for test environments (ASGITransport bypasses
    # lifespan). _lifespan replaces this with the real instance at startup.
    app.state.publish_bot = None  # _lifespan replaces with real Bot at startup

    return app


app = create_app()
