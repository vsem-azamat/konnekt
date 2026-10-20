"""The console's summary: the busiest chats of the last day, hour by hour."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, Message
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

    app.dependency_overrides[get_session] = _override_get_session
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


async def _seed(session_maker, messages: dict[int, list[datetime.datetime]]) -> None:
    async with session_maker() as session:
        session.add_all([Chat(id=chat_id, title=f"Chat {chat_id}") for chat_id in messages])
        n = 0
        for chat_id, times in messages.items():
            for at in times:
                n += 1
                message = Message(chat_id=chat_id, user_id=1, message_id=n)
                message.timestamp = at
                session.add(message)
        await session.commit()


async def _heatmap(client_factory) -> list[dict]:
    async with client_factory() as client:
        resp = await client.get("/api/stats/home")
    assert resp.status_code == 200, resp.text
    return resp.json()["chat_heatmap"]


async def test_the_busiest_chats_are_the_busiest_of_the_last_day(client_factory, db_session_maker) -> None:
    now = utc_now()
    await _seed(
        db_session_maker,
        {
            # Loud all week, quiet today.
            -1001: [now - datetime.timedelta(days=3)] * 10 + [now - datetime.timedelta(hours=1)],
            -1002: [now - datetime.timedelta(hours=2)] * 3,
        },
    )

    heatmap = await _heatmap(client_factory)

    assert [(chat["chat_id"], chat["total_messages"]) for chat in heatmap] == [(-1002, 3), (-1001, 1)]


async def test_each_busy_chat_counts_its_last_day_by_utc_hour(client_factory, db_session_maker) -> None:
    now = utc_now()
    at = [now - datetime.timedelta(hours=1), now - datetime.timedelta(hours=1), now - datetime.timedelta(hours=5)]
    await _seed(db_session_maker, {-1001: at})

    (chat,) = await _heatmap(client_factory)

    assert len(chat["hours"]) == 24
    expected = [0] * 24
    for moment in at:
        expected[moment.hour] += 1
    assert chat["hours"] == expected


async def test_a_chat_silent_for_a_day_is_not_among_the_busiest(client_factory, db_session_maker) -> None:
    await _seed(db_session_maker, {-1001: [utc_now() - datetime.timedelta(days=2)]})

    assert await _heatmap(client_factory) == []
