"""Tests for /api/users/{id}/block — global ban/unban via blacklist service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from app.core.config import settings
from app.db.models import ModerationEvent, User
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_publish_bot, get_session

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    fake_bot = AsyncMock()

    async def _override_publish_bot():
        return fake_bot

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_publish_bot] = _override_publish_bot
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make, fake_bot
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_publish_bot, None)


async def test_block_marks_user_blocked(client_factory, db_session_maker) -> None:
    make, _bot = client_factory
    async with db_session_maker() as s:
        s.add(User(id=42, username="alice"))
        await s.commit()

    async with make() as client:
        resp = await client.post("/api/users/42/block", json={"revoke_messages": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["blocked"] is True

    async with db_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == 42))).scalar_one()
        assert u.blocked is True


async def test_block_creates_user_when_unknown(client_factory, db_session_maker) -> None:
    """Unknown user_id (never seen before) should still produce a User row in
    blacklisted state — same semantics as the bot's /ban command."""
    make, _bot = client_factory
    async with make() as client:
        resp = await client.post("/api/users/99/block", json={})
    assert resp.status_code == 200, resp.text

    async with db_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == 99))).scalar_one()
        assert u.blocked is True


async def test_unblock_clears_flag(client_factory, db_session_maker) -> None:
    make, _bot = client_factory
    async with db_session_maker() as s:
        s.add(User(id=43, username="bob", blocked=True))
        await s.commit()

    async with make() as client:
        resp = await client.delete("/api/users/43/block")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["blocked"] is False

    async with db_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == 43))).scalar_one()
        assert u.blocked is False


async def test_unblock_404_when_user_unknown(client_factory) -> None:
    make, _bot = client_factory
    async with make() as client:
        resp = await client.delete("/api/users/99999/block")
    assert resp.status_code == 404


@pytest.mark.parametrize("user_id", [1, 2])
async def test_a_super_admin_cannot_be_banned(client_factory, db_session_maker, user_id: int) -> None:
    """Not themselves, and not each other.

    A blacklisted account's every message is dropped, private ones to the bot
    included, so a super admin banned by one tap in the console would lose the
    bot and the console with it. Refused here rather than hidden in the UI.
    """
    make, bot = client_factory
    settings.admin.super_admins = [1, 2]

    async with make() as client:
        resp = await client.post(f"/api/users/{user_id}/block", json={"revoke_messages": True})

    assert resp.status_code == 400, resp.text
    bot.ban_chat_member.assert_not_called()
    async with db_session_maker() as s:
        assert not (await s.scalars(select(ModerationEvent))).all(), "a refused ban is not on the record"
    async with db_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        assert u is None or u.blocked is False


async def test_the_blacklist_lists_the_blocked_most_recently_changed_first(client_factory, db_session_maker) -> None:
    """What /blacklist shows in the bot, for the console: who, and when the row last changed."""
    import datetime

    make, _bot = client_factory
    async with db_session_maker() as s:
        s.add_all(
            [
                User(id=61, username="old_spammer", blocked=True),
                User(id=62, username="new_spammer", first_name="Ivan", blocked=True),
                User(id=63, username="fine"),
            ]
        )
        await s.commit()
        old = (await s.execute(select(User).where(User.id == 61))).scalar_one()
        old.modified_at = datetime.datetime(2026, 1, 1)
        await s.commit()

    async with make() as client:
        resp = await client.get("/api/users/blocked")

    assert resp.status_code == 200, resp.text
    rows = resp.json()
    ids = [row["user_id"] for row in rows]
    assert 63 not in ids
    assert ids.index(62) < ids.index(61)
    newest = rows[ids.index(62)]
    assert newest["username"] == "new_spammer"
    assert newest["first_name"] == "Ivan"
    assert "changed_at" in newest


async def test_the_blacklist_is_for_super_admins(db_session_maker) -> None:
    from app.webapi.deps import get_session, require_super_admin

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    # The suite signs everybody in; this test is about who is not.
    app.dependency_overrides.pop(require_super_admin, None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/users/blocked")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 401


async def test_console_bans_and_unbans_are_on_the_record(client_factory, db_session_maker) -> None:
    """Who did it and from where, like /banall."""
    make, _bot = client_factory
    async with make() as client:
        assert (await client.post("/api/users/45/block", json={})).status_code == 200
        assert (await client.delete("/api/users/45/block")).status_code == 200

    async with db_session_maker() as s:
        events = (
            await s.scalars(
                select(ModerationEvent).where(ModerationEvent.target_user_id == 45).order_by(ModerationEvent.id)
            )
        ).all()
    assert [(e.action, e.source, e.actor_id, e.chat_id) for e in events] == [
        ("blacklist", "console", 1, None),
        ("unblacklist", "console", 1, None),
    ]
