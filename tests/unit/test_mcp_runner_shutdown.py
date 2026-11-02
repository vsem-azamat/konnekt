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


async def test_a_connected_client_does_not_hold_the_shutdown_past_its_bound(monkeypatch) -> None:
    """A streamable-HTTP client keeps a GET open; uvicorn would wait for it forever."""
    from app.core.config import settings
    from app.mcp import runner

    monkeypatch.setattr(settings.mcp, "host", "127.0.0.1")
    monkeypatch.setattr(settings.mcp, "port", 0)
    events: list[str] = []
    streaming = asyncio.Event()

    async def app(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    events.append("shutdown")
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x", "more_body": True})
        streaming.set()
        await asyncio.Event().wait()

    server = runner._build_server(app)
    task = asyncio.create_task(serve_until_cancelled(server))
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /mcp HTTP/1.1\r\nHost: x\r\n\r\n")
    await streaming.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=runner._SHUTDOWN_SECONDS + 2)

    assert events == ["shutdown"]
    writer.close()
