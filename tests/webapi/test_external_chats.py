"""`POST /api/chats/external`: listing a chat the bot is not in.

Such a chat never arrives on its own, because nothing tells the bot it exists.
The console names it by its public link and Telegram, asked by username,
supplies the id and the title, so nobody types a Telegram id by hand and
nothing about the chat is hardcoded anywhere.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    ClientDecodeError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
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


@pytest.mark.parametrize("link", ["@cvut_fjfi", "cvut_fjfi", "t.me/cvut_fjfi", " https://t.me/cvut_fjfi/ "])
async def test_a_username_is_taken_in_any_of_its_usual_spellings(client_factory, db_session_maker, link) -> None:
    make, holder = client_factory

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": link})

    assert resp.status_code == 201
    holder["bot"].get_chat.assert_awaited_once_with("@cvut_fjfi")
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert chat.public_link == "https://t.me/cvut_fjfi"


@pytest.mark.parametrize(
    "link",
    [
        "https://t.me/+AbCdEfGhIjKl",
        "https://t.me/joinchat/AbCdEfGhIjKl",
        "javascript:alert(1)",
        "https://example.com/x",
    ],
)
async def test_a_link_that_is_not_a_public_username_is_refused(client_factory, link) -> None:
    """Telegram resolves a username for anybody; an invite only for whoever joins through it."""
    make, holder = client_factory

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": link})

    assert (resp.status_code, resp.json()["detail"]) == (422, "not_public")
    holder["bot"].get_chat.assert_not_awaited()


async def test_a_username_telegram_does_not_know_is_refused(client_factory, db_session_maker) -> None:
    make, holder = client_factory
    holder["bot"].get_chat = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/nobody_here"})

    assert (resp.status_code, resp.json()["detail"]) == (422, "not_found")
    async with db_session_maker() as s:
        assert (await s.get(Chat, FJFI)) is None


async def test_a_person_is_not_listed(client_factory) -> None:
    make, holder = client_factory
    holder["bot"] = _bot(kind="private")

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/felexams"})

    assert (resp.status_code, resp.json()["detail"]) == (422, "not_a_group")


async def test_a_channel_is_listed_and_the_catalogue_says_it_is_one(client_factory, db_session_maker) -> None:
    make, holder = client_factory
    holder["bot"] = _bot(title="FEL exams", kind="channel")

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/felexams"})
        rows = (await client.get("/api/public/catalog")).json()

    assert (resp.status_code, resp.json()["kind"]) == (201, "channel")
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert chat.kind == Chat.KIND_CHANNEL
    assert [(row["title"], row["kind"]) for row in rows] == [("FEL exams", "channel")]


@pytest.mark.parametrize("kind", ["group", "supergroup"])
async def test_either_kind_of_group_is_a_group(client_factory, db_session_maker, kind) -> None:
    make, holder = client_factory
    holder["bot"] = _bot(kind=kind)

    async with make() as client:
        await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})
        rows = (await client.get("/api/public/catalog")).json()

    assert [row["kind"] for row in rows] == ["group"]


@pytest.mark.parametrize(
    "error",
    [
        TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=30),
        TelegramNetworkError(method=MagicMock(), message="timeout"),
        TelegramServerError(method=MagicMock(), message="bad gateway"),
        ClientDecodeError("not json", ValueError("x"), "<html>502</html>"),
    ],
)
async def test_telegram_failing_is_not_the_link_s_fault(client_factory, monkeypatch, error) -> None:
    """Said at once and as a failure to retry: a request does not sit out a flood wait."""
    make, holder = client_factory
    holder["bot"].get_chat = AsyncMock(side_effect=error)
    slept = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", slept)

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    assert (resp.status_code, resp.json()["detail"]) == (503, "telegram_unavailable")
    holder["bot"].get_chat.assert_awaited_once()
    slept.assert_not_awaited()


async def test_a_chat_already_known_is_left_as_it_is(client_factory, db_session_maker) -> None:
    """Adding by link must never be a way to switch moderation off in a chat we run."""
    make, _ = client_factory
    async with db_session_maker() as s:
        s.add(Chat(id=FJFI, title="Ours", resource_status=Chat.STATUS_APPROVED))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    assert (resp.status_code, resp.json()["detail"]) == (409, "already_known")
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert chat.resource_status == Chat.STATUS_APPROVED


async def test_a_chat_the_bot_records_meanwhile_is_left_as_it_is(client_factory, db_session_maker) -> None:
    """The row can appear between the check and the insert: the bot was just added there."""
    make, holder = client_factory
    found = MagicMock(id=FJFI, title="ČVUT FJFI", type="supergroup", is_forum=False)

    async def lookup_while_the_bot_joins(_username):
        async with db_session_maker() as s:
            s.add(Chat(id=FJFI, title="Ours", resource_status=Chat.STATUS_DISCOVERED))
            await s.commit()
        return found

    holder["bot"].get_chat = AsyncMock(side_effect=lookup_while_the_bot_joins)

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    assert (resp.status_code, resp.json()["detail"]) == (409, "already_known")


async def test_the_insert_itself_refusing_a_known_chat_is_a_409(client_factory, db_session_maker, monkeypatch) -> None:
    """The look-before-insert can miss a row written a moment later; the primary key does not."""
    from sqlalchemy.ext.asyncio import AsyncSession

    make, _ = client_factory
    async with db_session_maker() as s:
        s.add(Chat(id=FJFI, title="Ours", resource_status=Chat.STATUS_APPROVED))
        await s.commit()

    async def looked_too_early(self, entity, ident, **kwargs):
        return None

    monkeypatch.setattr(AsyncSession, "get", looked_too_early)

    async with make() as client:
        resp = await client.post("/api/chats/external", json={"public_link": "https://t.me/cvut_fjfi"})

    monkeypatch.undo()
    assert (resp.status_code, resp.json()["detail"]) == (409, "already_known")
    async with db_session_maker() as s:
        chat = await s.get(Chat, FJFI)
    assert chat is not None
    assert chat.resource_status == Chat.STATUS_APPROVED
