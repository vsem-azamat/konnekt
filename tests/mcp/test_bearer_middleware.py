"""The only authentication in front of the control plane.

Everything else in tests/mcp calls the tools directly, past this middleware,
so these are what says a request without the token never reaches a tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from app.mcp.server import BearerTokenMiddleware
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from starlette.types import Message, Scope

pytestmark = pytest.mark.asyncio

TOKEN = "s3cret-token"  # noqa: S105 — test fixture


async def _nothing() -> Message:
    return {"type": "http.disconnect"}


def _scope(**fields: Any) -> Scope:
    return cast("Scope", fields)


class _Tool:
    """Stands in for the MCP transport: records whether anything got through."""

    def __init__(self) -> None:
        self.reached = 0

    async def __call__(self, scope, receive, send) -> None:
        self.reached += 1
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


async def _get(headers: list[tuple[str, str]]) -> tuple[int, _Tool]:
    tool = _Tool()
    app = BearerTokenMiddleware(tool, TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp") as client:
        response = await client.request("POST", "/mcp", headers=headers)
    return response.status_code, tool


async def test_the_right_token_gets_through() -> None:
    status, tool = await _get([("Authorization", f"Bearer {TOKEN}")])

    assert (status, tool.reached) == (200, 1)


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Authorization", "Bearer")],
        [("Authorization", "Bearer wrong")],
        [("Authorization", f"Basic {TOKEN}")],
        [("Authorization", TOKEN)],
        # Two credentials have no agreed meaning; intermediaries disagree on which wins.
        [("Authorization", f"Bearer {TOKEN}"), ("Authorization", "Bearer wrong")],
        [("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")],
        [("Authorization", "Bearer s3cret-tokeN")],
    ],
)
async def test_anything_else_is_refused_before_the_tools(headers) -> None:
    status, tool = await _get(headers)

    assert (status, tool.reached) == (401, 0)


async def test_the_refusal_says_how_to_authenticate() -> None:
    app = BearerTokenMiddleware(_Tool(), TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp") as client:
        response = await client.post("/mcp")

    assert response.headers["www-authenticate"] == "Bearer"


async def test_an_empty_token_is_not_a_configuration() -> None:
    """compare_digest of two empty strings succeeds: an empty token is an open door."""
    with pytest.raises(ValueError, match="non-empty"):
        BearerTokenMiddleware(_Tool(), "")


async def test_a_websocket_is_closed_unauthenticated() -> None:
    """The transport speaks HTTP only; anything else is refused, not forwarded."""
    tool = _Tool()
    sent: list[dict] = []

    async def send(message: Message) -> None:
        sent.append(dict(message))

    scope = _scope(type="websocket", headers=[(b"authorization", f"Bearer {TOKEN}".encode())])
    await BearerTokenMiddleware(tool, TOKEN)(scope, _nothing, send)

    assert tool.reached == 0
    assert sent == [{"type": "websocket.close", "code": 1008}]


async def test_lifespan_reaches_the_transport() -> None:
    tool = _Tool()

    async def send(_message: Message) -> None:
        return None

    await BearerTokenMiddleware(tool, TOKEN)(_scope(type="lifespan"), _nothing, send)

    assert tool.reached == 1


async def test_a_non_ascii_credential_is_refused_without_raising() -> None:
    tool = _Tool()
    sent: list[dict] = []

    async def send(message: Message) -> None:
        sent.append(dict(message))

    scope = _scope(type="http", headers=[(b"authorization", "Bearer ключ".encode())])
    await BearerTokenMiddleware(tool, TOKEN)(scope, _nothing, send)

    assert tool.reached == 0
    assert sent[0]["status"] == 401
