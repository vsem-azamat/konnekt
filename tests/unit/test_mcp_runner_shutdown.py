"""The MCP plane stops the way uvicorn expects, so a deploy logs no traceback."""

from __future__ import annotations

import asyncio
import logging

import pytest
import uvicorn
from app.mcp.runner import serve_until_cancelled

pytestmark = pytest.mark.asyncio


async def test_cancelling_the_plane_runs_its_lifespan_shutdown(caplog) -> None:
    events: list[str] = []

    async def app(scope, receive, send) -> None:
        assert scope["type"] == "lifespan"
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                events.append("startup")
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                events.append("shutdown")
                await send({"type": "lifespan.shutdown.complete"})
                return

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, lifespan="on"))
    task = asyncio.create_task(serve_until_cancelled(server))
    while not server.started:
        await asyncio.sleep(0.01)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert events == ["startup", "shutdown"]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
