"""The ads queue: a moderator marks each hit, and what is marked leaves it."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, SpamPing, User
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


async def _seed(session_maker, *pings: SpamPing, chats=(-1001,), users: tuple[User, ...] = ()) -> list[int]:
    async with session_maker() as session:
        session.add_all([Chat(id=chat_id, title=f"Chat {chat_id}") for chat_id in chats])
        session.add_all(users)
        session.add_all(pings)
        await session.commit()
        return [ping.id for ping in pings]


def _ping(*, chat_id: int = -1001, user_id: int = 42, ago: datetime.timedelta = datetime.timedelta(0)) -> SpamPing:
    return SpamPing(
        chat_id=chat_id,
        user_id=user_id,
        message_id=100,
        kind="link",
        matches=["t.me/promo"],
        snippet="earn 300$ a day",
        detected_at=utc_now() - ago,
    )


async def _ids(client: AsyncClient, **params) -> list[int]:
    resp = await client.get("/api/spam/pings", params=params)
    assert resp.status_code == 200, resp.text
    return [ping["id"] for ping in resp.json()]


async def test_a_hit_marked_not_an_ad_leaves_the_queue_and_is_kept_for_the_detector(
    client_factory, db_session_maker
) -> None:
    first, second = await _seed(db_session_maker, _ping(), _ping())

    async with client_factory() as client:
        resp = await client.post(f"/api/spam/pings/{first}/review", json={"verdict": "not_ad"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["verdict"] == "not_ad"

        assert await _ids(client, status="unreviewed") == [second]
        assert await _ids(client, status="not_ad") == [first]
        assert sorted(await _ids(client)) == [first, second]


async def test_a_hit_marked_done_leaves_the_queue_but_is_not_called_a_false_alarm(
    client_factory, db_session_maker
) -> None:
    (ping,) = await _seed(db_session_maker, _ping())

    async with client_factory() as client:
        resp = await client.post(f"/api/spam/pings/{ping}/review", json={"verdict": "done"})
        assert resp.status_code == 200, resp.text

        assert await _ids(client, status="unreviewed") == []
        assert await _ids(client, status="not_ad") == []


async def test_the_review_records_who_marked_it_and_when(client_factory, db_session_maker) -> None:
    (ping,) = await _seed(db_session_maker, _ping())

    async with client_factory() as client:
        await client.post(f"/api/spam/pings/{ping}/review", json={"verdict": "not_ad"})

    async with db_session_maker() as session:
        row = await session.get(SpamPing, ping)
        assert row is not None
        assert row.reviewed_by == 1
        assert row.reviewed_at is not None


async def test_a_banned_authors_hits_are_answered_already(client_factory, db_session_maker) -> None:
    """A ban is the moderator's verdict on every hit of theirs: none of them
    waits in the queue, and nothing has to be written to each to say so."""
    banned, kept = await _seed(
        db_session_maker,
        _ping(user_id=7),
        _ping(user_id=8),
        users=(User(id=7, blocked=True), User(id=8)),
    )

    async with client_factory() as client:
        assert await _ids(client, status="unreviewed") == [kept]
        assert banned in await _ids(client, status="all")


async def test_reviewing_an_unknown_hit_is_404(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.post("/api/spam/pings/999/review", json={"verdict": "done"})
    assert resp.status_code == 404


async def test_a_verdict_outside_the_two_is_refused(client_factory, db_session_maker) -> None:
    (ping,) = await _seed(db_session_maker, _ping())
    async with client_factory() as client:
        resp = await client.post(f"/api/spam/pings/{ping}/review", json={"verdict": "ad"})
    assert resp.status_code == 422


async def test_the_period_counts_back_from_now(client_factory, db_session_maker) -> None:
    today, last_week, last_month = await _seed(
        db_session_maker,
        _ping(ago=datetime.timedelta(hours=2)),
        _ping(ago=datetime.timedelta(days=3)),
        _ping(ago=datetime.timedelta(days=20)),
    )

    async with client_factory() as client:
        assert await _ids(client, days=1) == [today]
        assert await _ids(client, days=7) == [today, last_week]
        assert await _ids(client) == [today, last_week, last_month]


async def test_the_chat_filter_and_the_queue_combine(client_factory, db_session_maker) -> None:
    here, there = await _seed(db_session_maker, _ping(chat_id=-1001), _ping(chat_id=-1002), chats=(-1001, -1002))

    async with client_factory() as client:
        assert await _ids(client, status="unreviewed", chat_id=-1002) == [there]
        assert here not in await _ids(client, status="unreviewed", chat_id=-1002)


async def test_pages_follow_one_another_without_a_gap_or_a_repeat(client_factory, db_session_maker) -> None:
    # Two hits in the same second: the page boundary must not split or drop them.
    same = utc_now() - datetime.timedelta(hours=1)
    pings = [_ping(ago=datetime.timedelta(minutes=minutes)) for minutes in range(5)]
    pings[2].detected_at = pings[3].detected_at = same
    ids = await _seed(db_session_maker, *pings)

    async with client_factory() as client:
        first = await _ids(client, limit=2)
        second = await _ids(client, limit=2, before_id=first[-1])
        third = await _ids(client, limit=2, before_id=second[-1])

    seen = first + second + third
    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen))
    assert len(third) == 1


async def test_the_summary_counts_what_waits_in_the_queue(client_factory, db_session_maker) -> None:
    reviewed, _waiting, _also_waiting, _banned = await _seed(
        db_session_maker,
        _ping(),
        _ping(),
        _ping(ago=datetime.timedelta(days=30)),
        _ping(user_id=7),
        users=(User(id=7, blocked=True),),
    )

    async with client_factory() as client:
        await client.post(f"/api/spam/pings/{reviewed}/review", json={"verdict": "done"})
        resp = await client.get("/api/stats/home")

    assert resp.status_code == 200, resp.text
    assert resp.json()["spam_pings"]["unreviewed"] == 2
