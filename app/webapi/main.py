"""FastAPI app factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.alerts import AlertHandler
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.webapi.deps import require_super_admin
from app.webapi.origin_guard import DEV_ORIGINS, RequireOurOrigin
from app.webapi.request_log import RequestLog
from app.webapi.routes import (
    admin,
    audience,
    auth,
    auth_telegram,
    catalog,
    catalog_pass,
    chats,
    client_errors,
    health,
    join_check,
    metrics,
    public,
    search,
    seen,
    signals,
    spam,
    stats,
    users,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Without it structlog prints to stdout and nothing reaches the root logger:
# no JSON in production, no LOG_FILE_PATH, and no error alerts.
setup_logging()
# RequestLog writes the line for every request, with its id and its route;
# uvicorn's would be a second, poorer one.
logging.getLogger("uvicorn.access").disabled = True
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
    purge = asyncio.create_task(_purge_expired_sessions())
    try:
        yield
    finally:
        await auth_telegram.close_oidc_http()
        await catalog.close_catalog_http()
        purge.cancel()
        await asyncio.gather(purge, return_exceptions=True)
        await alerts.stop()
        await close_publish_bot(_app.state.publish_bot)


async def _purge_expired_sessions(interval_seconds: int = 3600) -> None:
    """Delete expired console sessions hourly; nothing else ever did."""
    from app.db.session import get_session_maker
    from app.webapi.auth import session_store

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with get_session_maker()() as session:
                await session_store.purge_expired(session)
        except Exception:
            logger.exception("session_purge_failed")


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

    # Inside CORS, so a refusal still carries its headers.
    app.add_middleware(RequireOurOrigin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.webapi.allowed_origins or DEV_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Outside the server-error middleware that FastAPI puts around everything,
    # which `add_middleware` cannot reach: a 500 then gets its id and one line.
    build = app.build_middleware_stack
    app.build_middleware_stack = lambda: RequestLog(build())  # ty: ignore[invalid-assignment]

    app.include_router(auth.router, prefix="/api")
    app.include_router(auth_telegram.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(public.router, prefix="/api")
    app.include_router(catalog_pass.router, prefix="/api")
    app.include_router(join_check.router, prefix="/api")
    app.include_router(seen.router, prefix="/api")
    app.include_router(client_errors.router, prefix="/api")
    # The console, guarded at the router: a route added here cannot forget to
    # ask, and the question comes before anything else a route depends on.
    console = [Depends(require_super_admin)]
    app.include_router(chats.router, prefix="/api", dependencies=console)
    app.include_router(spam.router, prefix="/api", dependencies=console)
    app.include_router(stats.router, prefix="/api", dependencies=console)
    app.include_router(signals.router, prefix="/api", dependencies=console)
    app.include_router(users.router, prefix="/api", dependencies=console)
    app.include_router(admin.router, prefix="/api", dependencies=console)
    app.include_router(audience.router, prefix="/api", dependencies=console)
    app.include_router(catalog.router, prefix="/api", dependencies=console)
    app.include_router(search.router, prefix="/api", dependencies=console)

    # Default no-op singleton for test environments (ASGITransport bypasses
    # lifespan). _lifespan replaces this with the real instance at startup.
    app.state.publish_bot = None  # _lifespan replaces with real Bot at startup

    return app


app = create_app()
