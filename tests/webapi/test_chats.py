"""Tests for /api/chats endpoints."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.db.models import Chat, ChatMemberSnapshot, Message
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    async def _override_get_telethon():
        return None  # no telethon in tests

    app.dependency_overrides[get_session] = _override_get_session
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


async def test_the_list_says_which_chats_the_bot_has_left(client_factory, db_session_maker) -> None:
    """A chat awaiting a decision the bot is no longer in has nothing to decide but switching it off."""
    gone = datetime.datetime(2026, 10, 1, 12, 0)
    async with db_session_maker() as session:
        chat = Chat(id=-1001, title="Gone")
        chat.bot_absent_at = gone
        session.add(chat)
        session.add(Chat(id=-1002, title="Here"))
        await session.commit()

    async with client_factory() as client:
        body = {c["title"]: c for c in (await client.get("/api/chats")).json()}

    assert body["Gone"]["bot_absent_at"].startswith("2026-10-01T12:00")
    assert body["Here"]["bot_absent_at"] is None

    async with client_factory() as client:
        detail = (await client.get("/api/chats/-1001")).json()

    # The chat page reads it from here, to offer only switching off.
    assert detail["bot_absent_at"].startswith("2026-10-01T12:00")


async def test_list_chats_returns_all(client_factory, db_session_maker) -> None:
    async with db_session_maker() as session:
        session.add(Chat(id=-1001, title="A"))
        session.add(Chat(id=-1002, title="B"))
        await session.commit()

    async with client_factory() as client:
        resp = await client.get("/api/chats")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    titles = sorted(c["title"] for c in body)
    assert titles == ["A", "B"]
    assert {c["resource_status"] for c in body} == {"discovered"}
    # member_count is None when telethon is absent
    assert all(c["member_count"] is None for c in body)


async def test_update_chat_resource_status(client_factory, db_session_maker) -> None:
    chat_id = -1003
    async with db_session_maker() as session:
        session.add(Chat(id=chat_id, title="Pending"))
        await session.commit()

    async with client_factory() as client:
        resp = await client.patch(f"/api/chats/{chat_id}", json={"resource_status": "approved"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["resource_status"] == "approved"

    async with db_session_maker() as session:
        chat = await session.get(Chat, chat_id)
        assert chat is not None
        assert chat.resource_status == "approved"


async def test_chat_detail_heatmap_aggregates_messages(client_factory, db_session_maker) -> None:
    chat_id = -1010
    # Anchor timestamps relative to "now" so they always fall inside the
    # endpoint's 7-day lookback window — fixed dates would expire and break
    # the test once the wall clock moved past them.
    from app.core.time import utc_now

    now = utc_now()
    base = (now - datetime.timedelta(days=2)).replace(hour=10, minute=30, second=0, microsecond=0)
    next_day = (base + datetime.timedelta(days=1)).replace(hour=15, minute=0)

    async with db_session_maker() as session:
        session.add(Chat(id=chat_id, title="C"))
        for i in range(3):
            msg = Message(chat_id=chat_id, user_id=1, message_id=i)
            msg.timestamp = base
            session.add(msg)
        msg = Message(chat_id=chat_id, user_id=1, message_id=99)
        msg.timestamp = next_day
        session.add(msg)
        await session.commit()

    async with client_factory() as client:
        resp = await client.get(f"/api/chats/{chat_id}")

    assert resp.status_code == 200
    body = resp.json()
    cells = {(c["weekday"], c["hour"]): c["count"] for c in body["heatmap"]}
    assert cells.get((base.weekday(), base.hour)) == 3
    assert cells.get((next_day.weekday(), next_day.hour)) == 1


async def test_chat_detail_returns_member_snapshots(client_factory, db_session_maker) -> None:
    chat_id = -1020
    base = datetime.datetime(2026, 4, 21, 12, 0)
    async with db_session_maker() as session:
        session.add(Chat(id=chat_id, title="D"))
        for hours_ago, count in [(72, 100), (48, 110), (24, 120), (0, 125)]:
            captured = base - datetime.timedelta(hours=hours_ago)
            session.add(ChatMemberSnapshot(chat_id=chat_id, member_count=count, captured_at=captured))
        await session.commit()

    async with client_factory() as client:
        resp = await client.get(f"/api/chats/{chat_id}")

    body = resp.json()
    counts = [p["member_count"] for p in body["member_snapshots"]]
    assert counts == [100, 110, 120, 125]  # ascending captured_at


async def test_chat_detail_404(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.get("/api/chats/999999")
    assert resp.status_code == 404


async def test_chat_detail_returns_recent_senders(client_factory, db_session_maker) -> None:
    """Recent senders aggregates message counts per user with their block flag."""
    from app.core.time import utc_now
    from app.db.models import User

    chat_id = -1030
    now = utc_now()
    async with db_session_maker() as session:
        session.add(Chat(id=chat_id, title="E"))
        session.add(User(id=501, username="alice", blocked=False))
        session.add(User(id=502, username="bob", blocked=True))
        for i in range(3):
            m = Message(chat_id=chat_id, user_id=501, message_id=100 + i)
            m.timestamp = now - datetime.timedelta(hours=i)
            session.add(m)
        m = Message(chat_id=chat_id, user_id=502, message_id=200)
        m.timestamp = now - datetime.timedelta(hours=1)
        session.add(m)
        await session.commit()

    async with client_factory() as client:
        resp = await client.get(f"/api/chats/{chat_id}")
    assert resp.status_code == 200
    body = resp.json()
    senders = {s["user_id"]: s for s in body["recent_senders"]}
    assert senders[501]["message_count"] == 3
    assert senders[501]["blocked"] is False
    assert senders[502]["blocked"] is True
