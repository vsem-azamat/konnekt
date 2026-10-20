"""The console's summary: the busiest chats of the last day, hour by hour."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.core.time import utc_now
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

    app.dependency_overrides[get_session] = _override_get_session
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


async def _seed(
    session_maker,
    messages: dict[int, list[datetime.datetime]],
    untitled: tuple[int, ...] = (),
    titles: dict[int, str] | None = None,
) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                Chat(id=chat_id, title=(titles or {}).get(chat_id, f"Chat {chat_id}"))
                for chat_id in messages
                if chat_id not in untitled
            ]
        )
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


async def test_busy_chats_tied_on_messages_go_by_title_and_a_chat_never_stored_comes_last(
    client_factory, db_session_maker
) -> None:
    """Titled so that their order is not the ids' (nor the grouping's)."""
    hour_ago = utc_now() - datetime.timedelta(hours=1)
    await _seed(
        db_session_maker,
        {-1003: [hour_ago], -1001: [hour_ago], -1002: [hour_ago]},
        untitled=(-1002,),
        titles={-1003: "Zeta", -1001: "Alpha"},
    )

    heatmap = await _heatmap(client_factory)

    assert [(chat["chat_id"], chat["title"]) for chat in heatmap] == [(-1001, "Alpha"), (-1003, "Zeta"), (-1002, None)]
    assert all(chat["total_messages"] == sum(chat["hours"]) for chat in heatmap)


# ── members ─────────────────────────────────────────────────────────────


async def _snapshots(session_maker, chat_id: int, status: str, counts: list[tuple[datetime.timedelta, int]]) -> None:
    now = utc_now()
    async with session_maker() as session:
        session.add(Chat(id=chat_id, title=f"Chat {chat_id}", resource_status=status))
        session.add_all(
            [ChatMemberSnapshot(chat_id=chat_id, member_count=count, captured_at=now - ago) for ago, count in counts]
        )
        await session.commit()


async def _deltas(client_factory) -> dict[int, tuple[int | None, int | None]]:
    async with client_factory() as client:
        resp = await client.get("/api/stats/home")
    assert resp.status_code == 200, resp.text
    return {entry["chat_id"]: (entry["delta_24h"], entry["delta_7d"]) for entry in resp.json()["members_delta"]}


H = datetime.timedelta(hours=1)
D = datetime.timedelta(days=1)


async def test_a_day_and_a_week_compare_with_the_count_closest_before_each(client_factory, db_session_maker) -> None:
    """Not the oldest count of the month: that made a day, a week and thirty
    days the same number."""
    await _snapshots(db_session_maker, -1001, "approved", [(29 * D, 100), (8 * D, 200), (25 * H, 300), (H, 400)])

    assert (await _deltas(client_factory))[-1001] == (100, 200)


async def test_a_count_just_inside_the_window_is_not_its_baseline(client_factory, db_session_maker) -> None:
    minute = datetime.timedelta(minutes=1)
    await _snapshots(db_session_maker, -1001, "approved", [(D + minute, 300), (D - minute, 350), (H, 400)])

    assert (await _deltas(client_factory))[-1001] == (100, None)


async def test_a_chat_whose_counts_stopped_moves_nowhere(client_factory, db_session_maker) -> None:
    """The newest count three hours old is not today's: the bot left, or
    stopped counting there."""
    await _snapshots(db_session_maker, -1001, "approved", [(8 * D, 100), (3 * H, 400)])

    assert (await _deltas(client_factory))[-1001] == (None, None)


async def test_only_the_chats_we_run_are_counted(client_factory, db_session_maker) -> None:
    await _snapshots(db_session_maker, -1001, "approved", [(2 * D, 100), (H, 110)])
    await _snapshots(db_session_maker, -1002, "discovered", [(2 * D, 100), (H, 900)])

    assert set(await _deltas(client_factory)) == {-1001}
