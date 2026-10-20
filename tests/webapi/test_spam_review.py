"""The ads queue: a moderator marks each hit, and what is marked leaves it."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

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
def client_factory(db_session_maker: async_sessionmaker[AsyncSession], fake_bot: AsyncMock, monkeypatch):
    from app.webapi.deps import get_publish_bot, get_session

    async def _override_get_session():
        async with db_session_maker() as session:
            yield session

    async def _override_publish_bot():
        return fake_bot

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_publish_bot] = _override_publish_bot
    monkeypatch.setattr(settings.admin, "super_admins", [1])
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


@pytest.fixture
def fake_bot() -> AsyncMock:
    return AsyncMock()


async def _seed(session_maker, *pings: SpamPing, chats=(-1001,), users: tuple[User, ...] = ()) -> list[int]:
    async with session_maker() as session:
        session.add_all([Chat(id=chat_id, title=f"Chat {chat_id}", resource_status="approved") for chat_id in chats])
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


async def test_a_ban_answers_every_hit_of_the_author(client_factory, db_session_maker) -> None:
    """A ban is the moderator's verdict on all of theirs: «ad», written once the
    ban took somewhere, and kept when the ban is lifted."""
    first, second, other = await _seed(db_session_maker, _ping(user_id=7), _ping(user_id=7), _ping(user_id=8))

    async with client_factory() as client:
        banned = await client.post("/api/users/7/block", json={"revoke_messages": False})
        assert banned.status_code == 200, banned.text
        assert banned.json()["failed_chats"] == []
        assert await _ids(client, status="unreviewed") == [other]
        await client.delete("/api/users/7/block")
        assert await _ids(client, status="unreviewed") == [other]

    async with db_session_maker() as session:
        for ping_id in (first, second):
            row = await session.get(SpamPing, ping_id)
            assert row is not None
            assert row.verdict == "ad"


async def test_a_ban_that_took_nowhere_answers_nothing(client_factory, db_session_maker, fake_bot) -> None:
    (ping,) = await _seed(db_session_maker, _ping(user_id=7))
    fake_bot.ban_chat_member.side_effect = RuntimeError("Telegram refused")

    async with client_factory() as client:
        banned = await client.post("/api/users/7/block", json={"revoke_messages": False})
        queue = await _ids(client, status="unreviewed")

    assert banned.status_code == 200, banned.text
    assert (banned.json()["failed_chats"], banned.json()["banned_in"]) == ([-1001], 0)
    assert queue == [ping]


async def test_a_ban_that_took_in_some_chats_answers_the_hits_and_names_the_rest(
    client_factory, db_session_maker, fake_bot
) -> None:
    (ping,) = await _seed(db_session_maker, _ping(user_id=7), chats=(-1001, -1002))

    async def ban(chat_id, user_id, **_):
        if chat_id == -1002:
            raise RuntimeError("Telegram refused")

    fake_bot.ban_chat_member.side_effect = ban

    async with client_factory() as client:
        banned = await client.post("/api/users/7/block", json={"revoke_messages": False})
        queue = await _ids(client, status="unreviewed")

    assert banned.status_code == 200, banned.text
    assert (banned.json()["failed_chats"], banned.json()["banned_in"]) == ([-1002], 1)
    assert queue == []
    async with db_session_maker() as session:
        row = await session.get(SpamPing, ping)
        assert row is not None
        # Whoever pressed it in the console: the ban is their answer.
        assert (row.verdict, row.reviewed_by) == ("ad", 1)


async def test_a_ban_with_no_chat_to_act_in_answers_nothing(client_factory, db_session_maker) -> None:
    async with db_session_maker() as session:
        session.add(_ping(user_id=7))
        await session.commit()

    async with client_factory() as client:
        banned = await client.post("/api/users/7/block", json={"revoke_messages": False})
        queue = await _ids(client, status="unreviewed")

    assert (banned.json()["failed_chats"], banned.json()["banned_in"]) == ([], 0)
    assert len(queue) == 1


@pytest.mark.parametrize("params", [{"before_id": 5}, {"before_at": "2026-10-20T10:00:00"}])
async def test_a_cursor_is_both_halves_or_none(client_factory, params) -> None:
    async with client_factory() as client:
        resp = await client.get("/api/spam/pings", params=params)
    assert resp.status_code == 422


async def test_a_cursor_with_a_zone_is_read_as_utc(client_factory, db_session_maker) -> None:
    older, newer = await _seed(
        db_session_maker, _ping(ago=datetime.timedelta(hours=3)), _ping(ago=datetime.timedelta(hours=1))
    )
    async with db_session_maker() as session:
        at = (await session.get(SpamPing, newer)).detected_at  # type: ignore[union-attr]
    prague = datetime.timezone(datetime.timedelta(hours=2))
    stamp = at.replace(tzinfo=datetime.UTC).astimezone(prague).isoformat()

    async with client_factory() as client:
        resp = await client.get("/api/spam/pings", params={"before_at": stamp, "before_id": newer})

    assert [ping["id"] for ping in resp.json()] == [older]


async def test_an_answered_hit_is_not_answered_again(client_factory, db_session_maker) -> None:
    """Two moderators on one hit: the first answer stands, the second is told."""
    (ping,) = await _seed(db_session_maker, _ping())

    async with client_factory() as client:
        first = await client.post(f"/api/spam/pings/{ping}/review", json={"verdict": "not_ad"})
        second = await client.post(f"/api/spam/pings/{ping}/review", json={"verdict": "done"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["verdict"] == "not_ad"
    async with db_session_maker() as session:
        row = await session.get(SpamPing, ping)
        assert row is not None
        assert row.verdict == "not_ad"


async def test_the_queue_counts_what_its_filters_show(client_factory, db_session_maker) -> None:
    await _seed(
        db_session_maker,
        _ping(chat_id=-1001),
        _ping(chat_id=-1002),
        _ping(chat_id=-1002, ago=datetime.timedelta(days=10)),
        chats=(-1001, -1002),
    )

    async with client_factory() as client:
        count = lambda **params: client.get("/api/spam/pings/unreviewed", params=params)  # noqa: E731
        assert (await count()).json() == {"count": 3}
        assert (await count(chat_id=-1002)).json() == {"count": 2}
        assert (await count(chat_id=-1002, days=7)).json() == {"count": 1}


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


async def _page(client: AsyncClient, after: dict | None, limit: int = 2) -> list[dict]:
    params: dict = {"limit": limit}
    if after is not None:
        params |= {"before_at": after["detected_at"], "before_id": after["id"]}
    resp = await client.get("/api/spam/pings", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_pages_follow_one_another_without_a_gap_or_a_repeat(client_factory, db_session_maker) -> None:
    # Two hits in the same second: the page boundary must not split or drop them.
    same = utc_now() - datetime.timedelta(hours=1)
    pings = [_ping(ago=datetime.timedelta(minutes=minutes)) for minutes in range(5)]
    pings[2].detected_at = pings[3].detected_at = same
    ids = await _seed(db_session_maker, *pings)

    async with client_factory() as client:
        first = await _page(client, None)
        second = await _page(client, first[-1])
        third = await _page(client, second[-1])

    seen = [ping["id"] for ping in first + second + third]
    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen))
    assert len(third) == 1


async def test_a_page_continues_after_a_hit_that_is_gone(client_factory, db_session_maker) -> None:
    """The retention purge, or an edit, can take the row the cursor names."""
    ids = await _seed(db_session_maker, *[_ping(ago=datetime.timedelta(minutes=minutes)) for minutes in range(3)])

    async with client_factory() as client:
        first = await _page(client, None, limit=1)
        async with db_session_maker() as session:
            gone = await session.get(SpamPing, first[0]["id"])
            await session.delete(gone)
            await session.commit()
        rest = await _page(client, first[0])

    assert [ping["id"] for ping in rest] == ids[1:]


async def test_the_summary_counts_what_waits_in_the_queue(client_factory, db_session_maker) -> None:
    banned = _ping(user_id=7)
    banned.verdict = "ad"
    reviewed, _waiting, _also_waiting, _banned = await _seed(
        db_session_maker, _ping(), _ping(), _ping(ago=datetime.timedelta(days=30)), banned
    )

    async with client_factory() as client:
        await client.post(f"/api/spam/pings/{reviewed}/review", json={"verdict": "done"})
        resp = await client.get("/api/stats/home")

    assert resp.status_code == 200, resp.text
    assert resp.json()["spam_pings"]["unreviewed"] == 2
