"""Serve the MCP control plane from inside the bot process.

The endpoint used to be mounted on the web API, which cannot reach the thing
the moderation tools depend on: the bot that sends confirmation keyboards and
owns their callbacks. Telegram delivers a button press back to the identity
that sent the message, so the confirmation tier only works from here.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Generator

logger = get_logger("mcp.runner")


def _build_server(app: Any) -> Any:
    """Wrap uvicorn so it leaves this process's signal handling alone.

    ``Server.serve()`` installs its own SIGINT/SIGTERM handlers through
    ``capture_signals()``. Here that would replace the ones aiogram's polling
    installed and leave the bot without a shutdown path, so the hook is
    neutralised rather than the signals shared.
    """
    import uvicorn

    class _BotOwnsSignals(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self) -> Generator[None, None, None]:
            yield

    config = uvicorn.Config(
        app,
        host=settings.mcp.host,
        port=settings.mcp.port,
        log_config=None,
        lifespan="on",
    )
    return _BotOwnsSignals(config)


async def run_mcp_server() -> None:
    """Run the token-protected MCP endpoint until cancelled.

    Returns immediately when MCP is inactive so the caller can add this to its
    task list unconditionally.
    """
    if not settings.mcp.active:
        logger.info("mcp_disabled")
        return

    from app.mcp.server import build_mcp_asgi_app

    server = _build_server(build_mcp_asgi_app(token=settings.mcp.token, path=settings.mcp.path))

    logger.info("mcp_serving", host=settings.mcp.host, port=settings.mcp.port, path=settings.mcp.path)
    try:
        await serve_until_cancelled(server)
    except asyncio.CancelledError:
        logger.info("mcp_cancelled")
        raise
    finally:
        logger.info("mcp_stopped")


# How long the plane gets to finish its lifespan once the bot is stopping.
_SHUTDOWN_SECONDS = 5.0


async def serve_until_cancelled(server: Any) -> None:
    """Serve until cancelled, then stop the way uvicorn stops itself.

    Cancelling ``serve()`` itself cut the ASGI lifespan off mid-wait, and
    uvicorn logged that as an error with a traceback on every deploy. Asked to
    exit instead, it runs the app's shutdown and returns.
    """
    serving = asyncio.ensure_future(server.serve())
    try:
        await asyncio.shield(serving)
    except asyncio.CancelledError:
        server.should_exit = True
        await asyncio.wait({serving}, timeout=_SHUTDOWN_SECONDS)
        serving.cancel()
        raise
