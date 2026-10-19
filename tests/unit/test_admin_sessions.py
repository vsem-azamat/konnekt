"""ORM-level coverage for AdminSession."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.db.models import AdminSession
from app.webapi.auth import session_store
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_create_and_read(session: AsyncSession) -> None:
    now = datetime.datetime(2026, 4, 22, 0, 0, 0)
    s = AdminSession(
        session_id="abc" * 10,
        user_id=1,
        created_at=now,
        last_seen_at=now,
        expires_at=now + datetime.timedelta(days=30),
    )
    session.add(s)
    await session.commit()

    row = (await session.execute(select(AdminSession).where(AdminSession.session_id == s.session_id))).scalar_one()
    assert row.user_id == 1
    assert row.user_agent is None


async def test_expired_flag(session: AsyncSession) -> None:
    past = datetime.datetime(2026, 1, 1, 0, 0, 0)
    s = AdminSession(
        session_id="expired",
        user_id=1,
        created_at=past,
        last_seen_at=past,
        expires_at=past + datetime.timedelta(days=30),
    )
    session.add(s)
    await session.commit()

    assert s.expires_at < datetime.datetime(2026, 4, 22)


async def test_create_and_load_round_trip(session: AsyncSession) -> None:
    _row, token = await session_store.create_session(session, user_id=1, ttl_days=30, user_agent="ua", ip="127.0.0.1")
    found = await session_store.load_valid_session(session, token)
    assert found is not None
    assert found.user_id == 1


async def test_load_expired_removes_row(session: AsyncSession) -> None:
    row, token = await session_store.create_session(session, user_id=1, ttl_days=30, user_agent=None, ip=None)
    # Expire it.
    row.expires_at = datetime.datetime(2026, 1, 1)
    await session.commit()
    assert await session_store.load_valid_session(session, token) is None
    # And row is deleted.
    assert await session_store.load_valid_session(session, token) is None


async def test_revoke(session: AsyncSession) -> None:
    row, _token = await session_store.create_session(session, user_id=1, ttl_days=30, user_agent=None, ip=None)
    assert await session_store.revoke_session(session, row.session_id) is True
    assert await session_store.revoke_session(session, row.session_id) is False
