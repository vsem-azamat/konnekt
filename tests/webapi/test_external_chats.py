"""`POST /api/chats/external`: listing a chat the bot is not in.

Such a chat never arrives on its own, because nothing tells the bot it exists.
The console names it by its public link and Telegram, asked by username,
supplies the id and the title, so nobody types a Telegram id by hand and
nothing about the chat is hardcoded anywhere.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.core.config import settings
from app.db.models import Chat
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

FJFI = -1001852850466


def _bot(*, chat_id: int = FJFI, title: str = "ČVUT FJFI", kind: str = "supergroup", forum: bool = False) -> MagicMock:
    bot = MagicMock()
    bot.get_chat = AsyncMock(return_value=MagicMock(id=chat_id, title=title, type=kind, is_forum=forum))
    return bot


@pytest.fixture
def client_factory(db_session_maker):
    from app.webapi.deps import get_publish_bot, get_session

    holder: dict[str, MagicMock] = {"bot": _bot()}

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    async def _override_publish_bot():
        return holder["bot"]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_publish_bot] = _override_publish_bot
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make, holder
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


async def test_a_public_chat_is_listed_as_external(client_factory, db_session_maker) -> None:
    make, holder = client_factory

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    assert resp.status_code == 201
    assert resp.json()["resource_status"] == "external"
    holder["bot"].get_chat.assert_awaited_once_with("@cvut_fjfi")
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert (chat.title, chat.public_link, chat.resource_status) == (
        "ČVUT FJFI",
        "https://t.me/cvut_fjfi",
        Chat.STATUS_EXTERNAL,
    )


async def test_it_shows_up_in_the_public_catalogue(client_factory) -> None:
    make, _ = client_factory

    async with make() as client:
        await client.get("/api/public/catalog")  # an answer remembered before the change
        await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})
        rows = (await client.get("/api/public/catalog")).json()

    assert [(row["title"], row["external"]) for row in rows] == [("ČVUT FJFI", True)]


@pytest.mark.parametrize("link", ["https://t.me/+AbCdEfGhIjKl", "https://t.me/joinchat/AbCdEfGhIjKl"])
async def test_an_invite_link_cannot_be_looked_up(client_factory, link) -> None:
    """Telegram resolves a username for anybody; an invite only for whoever joins through it."""
    make, holder = client_factory

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": link})

    assert resp.status_code == 422
    holder["bot"].get_chat.assert_not_awaited()


async def test_a_link_that_is_not_telegram_is_refused(client_factory) -> None:
    make, _ = client_factory

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "javascript:alert(1)"})

    assert resp.status_code == 422


async def test_a_username_telegram_does_not_know_is_refused(client_factory, db_session_maker) -> None:
    make, holder = client_factory
    holder["bot"].get_chat = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/nobody_here"})

    assert resp.status_code == 422
    async with db_session_maker() as s:
        assert (await s.get(Chat, FJFI)) is None


async def test_a_channel_is_not_a_chat(client_factory) -> None:
    make, holder = client_factory
    holder["bot"] = _bot(kind="channel")

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/felexams"})

    assert resp.status_code == 422


async def test_a_chat_already_known_is_left_as_it_is(client_factory, db_session_maker) -> None:
    """Adding by link must never be a way to switch moderation off in a chat we run."""
    make, _ = client_factory
    async with db_session_maker() as s:
        s.add(Chat(id=FJFI, title="Ours", resource_status=Chat.STATUS_APPROVED))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    assert resp.status_code == 409
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert chat.resource_status == Chat.STATUS_APPROVED
