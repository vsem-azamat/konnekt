"""`POST /api/chats/{id}/refresh`.

Refresh asks Telegram for a chat's title, photo and member count, all over the
Bot API. The title used to come through Telethon, which this process has never
had, so the button quietly refreshed everything except the one field somebody
presses it for.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramMigrateToChat
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


def _bot(*, title: str = "Как в Telegram", photo: str | None = "photo-file-id-1", members: int = 42) -> MagicMock:
    bot = MagicMock()
    bot.get_chat = AsyncMock(
        return_value=MagicMock(
            title=title,
            photo=MagicMock(big_file_id=photo, small_file_id="small") if photo else None,
        )
    )
    bot.get_chat_member_count = AsyncMock(return_value=members)
    bot.download = AsyncMock(return_value=io.BytesIO(b"\xff\xd8\xff\xe0jpegbytes"))
    return bot


@pytest.fixture
def client_factory(db_session_maker):
    from app.webapi.deps import get_publish_bot, get_session

    bot_holder: dict[str, MagicMock] = {"bot": _bot()}

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    async def _override_publish_bot():
        return bot_holder["bot"]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_publish_bot] = _override_publish_bot
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make, bot_holder
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


async def test_refresh_caches_photo_file_id(client_factory, db_session_maker) -> None:
    make, _bot_holder = client_factory
    async with db_session_maker() as s:
        s.add(Chat(id=-7001, title="A"))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7001/refresh")

    assert resp.status_code == 200
    body = resp.json()
    assert body["has_photo"] is True
    assert body["last_synced_at"] is not None

    async with db_session_maker() as s:
        chat = (await s.execute(select(Chat).where(Chat.id == -7001))).scalar_one()
    assert chat.photo_file_id == "photo-file-id-1"
    assert chat.last_synced_at is not None


async def test_refresh_clears_the_photo_when_the_chat_has_none_now(client_factory, db_session_maker) -> None:
    """`getChat` leaves the photo out when it was removed: that answer is the news."""
    make, bot_holder = client_factory
    bot_holder["bot"] = _bot(photo=None)
    async with db_session_maker() as s:
        chat = Chat(id=-7002, title="B")
        chat.photo_file_id = "stale-cached-id"
        s.add(chat)
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7002/refresh")

    assert resp.status_code == 200
    async with db_session_maker() as s:
        chat = (await s.execute(select(Chat).where(Chat.id == -7002))).scalar_one()
    assert chat.photo_file_id is None


async def test_refresh_keeps_the_cached_photo_when_telegram_does_not_answer(client_factory, db_session_maker) -> None:
    """A hiccup is not a removal: no answer means the icon stays."""
    make, bot_holder = client_factory
    bot_holder["bot"].get_chat = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))
    async with db_session_maker() as s:
        chat = Chat(id=-7002, title="B")
        chat.photo_file_id = "stale-cached-id"
        s.add(chat)
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7002/refresh")

    assert resp.status_code == 200
    async with db_session_maker() as s:
        chat = (await s.execute(select(Chat).where(Chat.id == -7002))).scalar_one()
    assert chat.photo_file_id == "stale-cached-id"


async def test_refresh_syncs_the_title(client_factory, db_session_maker) -> None:
    """The reason somebody presses the button."""
    make, bot_holder = client_factory
    bot_holder["bot"] = _bot(title="Renamed Live")
    async with db_session_maker() as s:
        s.add(Chat(id=-7003, title="Old DB Title"))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7003/refresh")

    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Live"


async def test_refresh_returns_a_fresh_member_count(client_factory, db_session_maker) -> None:
    """Read live rather than from the hourly snapshot: a button marked refresh
    that hands back an hour-old number has not refreshed anything."""
    make, bot_holder = client_factory
    bot_holder["bot"] = _bot(members=1234)
    async with db_session_maker() as s:
        s.add(Chat(id=-7006, title="E"))
        s.add(ChatMemberSnapshot(chat_id=-7006, member_count=11))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7006/refresh")

    assert resp.json()["member_count"] == 1234


async def test_refresh_falls_back_to_the_last_snapshot(client_factory, db_session_maker) -> None:
    """Telegram declining is not a reason to report that nobody is there."""
    make, bot_holder = client_factory
    bot = _bot()
    bot.get_chat_member_count = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="nope"))
    bot_holder["bot"] = bot
    async with db_session_maker() as s:
        s.add(Chat(id=-7007, title="F"))
        s.add(ChatMemberSnapshot(chat_id=-7007, member_count=11))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7007/refresh")

    assert resp.json()["member_count"] == 11


async def test_refresh_of_a_chat_the_bot_is_not_in_falls_back_too(client_factory, db_session_maker) -> None:
    make, bot_holder = client_factory
    bot = _bot()
    bot.get_chat_member_count = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))
    bot_holder["bot"] = bot
    async with db_session_maker() as s:
        s.add(Chat(id=-7008, title="G"))
        s.add(ChatMemberSnapshot(chat_id=-7008, member_count=11))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7008/refresh")

    assert resp.status_code == 200
    assert resp.json()["member_count"] == 11


async def test_refresh_that_gets_a_count_clears_the_absent_mark(client_factory, db_session_maker) -> None:
    """The bot was added and somebody pressed refresh: the hourly counts resume on the next tick."""
    make, bot_holder = client_factory
    bot_holder["bot"] = _bot(members=50)
    async with db_session_maker() as s:
        chat = Chat(id=-7009, title="H")
        chat.bot_absent_at = utc_now()
        s.add(chat)
        await s.commit()

    async with make() as client:
        await client.post("/api/chats/-7009/refresh")

    async with db_session_maker() as s:
        assert (await s.get(Chat, -7009)).bot_absent_at is None


async def test_refresh_of_a_group_that_became_a_supergroup_says_where_it_went(client_factory, db_session_maker) -> None:
    make, bot_holder = client_factory
    bot = _bot()
    bot.get_chat_member_count = AsyncMock(
        side_effect=TelegramMigrateToChat(method=MagicMock(), message="upgraded", migrate_to_chat_id=-1004394473356)
    )
    bot_holder["bot"] = bot
    async with db_session_maker() as s:
        s.add(Chat(id=-7010, title="Old"))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/chats/-7010/refresh")

    assert resp.status_code == 200
    assert (resp.json()["member_count"], resp.json()["resource_status"]) == (None, "disabled")
    async with db_session_maker() as s:
        assert (await s.get(Chat, -7010)).migrated_to_chat_id == -1004394473356
        assert await s.get(Chat, -1004394473356) is not None


async def test_refresh_returns_404_for_unknown_chat(client_factory) -> None:
    make, _bot_holder = client_factory
    async with make() as client:
        resp = await client.post("/api/chats/-9999/refresh")
    assert resp.status_code == 404
