"""Tests for /api/admin — sessions panel + system status."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.db.models import AdminSession
from app.webapi.auth.session_store import public_id
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    settings.admin.super_admins = [1]
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)


async def _seed_session(s: AsyncSession, *, session_id: str, user_id: int = 1) -> None:
    now = datetime.datetime(2026, 4, 27, 12, 0, 0)
    s.add(
        AdminSession(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + datetime.timedelta(days=30),
            user_agent="test-agent",
            ip="127.0.0.1",
        )
    )
    await s.commit()


async def test_list_sessions_returns_only_callers(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        await _seed_session(s, session_id="mine-1", user_id=1)
        await _seed_session(s, session_id="mine-2", user_id=1)
        await _seed_session(s, session_id="other", user_id=999)

    async with client_factory() as client:
        resp = await client.get("/api/admin/sessions")
    assert resp.status_code == 200, resp.text
    ids = sorted(r["id"] for r in resp.json())
    assert ids == sorted([public_id("mine-1"), public_id("mine-2")])


async def test_list_sessions_never_returns_a_session_token(client_factory, db_session_maker) -> None:
    """The cookie is HttpOnly so script cannot read it; JSON must not hand it back."""
    async with db_session_maker() as s:
        await _seed_session(s, session_id="secret-cookie-value")

    async with client_factory() as client:
        resp = await client.get("/api/admin/sessions")
    assert "secret-cookie-value" not in resp.text
    assert "session_id" not in resp.json()[0]


async def test_list_sessions_marks_current(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        await _seed_session(s, session_id="active-token")
        await _seed_session(s, session_id="other-token")

    async with client_factory() as client:
        client.cookies.set(settings.webapi.session_cookie_name, "active-token")
        resp = await client.get("/api/admin/sessions")
    rows = {r["id"]: r for r in resp.json()}
    assert rows[public_id("active-token")]["is_current"] is True
    assert rows[public_id("other-token")]["is_current"] is False


async def test_revoke_session_deletes_row(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        await _seed_session(s, session_id="to-revoke")

    async with client_factory() as client:
        resp = await client.delete(f"/api/admin/sessions/{public_id('to-revoke')}")
    assert resp.status_code == 204

    async with db_session_maker() as s:
        gone = (
            await s.execute(select(AdminSession).where(AdminSession.session_id == "to-revoke"))
        ).scalar_one_or_none()
        assert gone is None


async def test_revoke_does_not_take_a_token_in_the_url(client_factory, db_session_maker) -> None:
    """A token in the path lands in the access log."""
    async with db_session_maker() as s:
        await _seed_session(s, session_id="to-revoke")

    async with client_factory() as client:
        resp = await client.delete("/api/admin/sessions/to-revoke")
    assert resp.status_code == 404


async def test_revoke_current_session_400(client_factory, db_session_maker) -> None:
    async with db_session_maker() as s:
        await _seed_session(s, session_id="active-token")

    async with client_factory() as client:
        client.cookies.set(settings.webapi.session_cookie_name, "active-token")
        resp = await client.delete(f"/api/admin/sessions/{public_id('active-token')}")
    assert resp.status_code == 400
    assert "cannot close itself" in resp.json()["detail"]


async def test_revoke_session_404_when_unknown(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.delete("/api/admin/sessions/does-not-exist")
    assert resp.status_code == 404


async def test_revoke_other_users_session_404(client_factory, db_session_maker) -> None:
    """Only the caller's own sessions are looked at, so another's is simply not found."""
    async with db_session_maker() as s:
        await _seed_session(s, session_id="someone-elses", user_id=999)

    async with client_factory() as client:
        resp = await client.delete(f"/api/admin/sessions/{public_id('someone-elses')}")
    assert resp.status_code == 404

    async with db_session_maker() as s:
        assert await s.get(AdminSession, "someone-elses") is not None


async def test_get_system_status(client_factory) -> None:
    settings.webapi.public_url = "http://localhost:5173"
    settings.webapi.session_ttl_days = 30
    async with client_factory() as client:
        resp = await client.get("/api/admin/system")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["super_admin_ids"] == [1]
    assert body["session_ttl_days"] == 30
    flag_names = {f["name"] for f in body["feature_flags"]}
    assert flag_names == {
        "auth_telegram_webapp",
        "ad_detector_enabled",
    }
