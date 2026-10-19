"""CRUD for ``admin_sessions``.

Session IDs are generated with :func:`secrets.token_urlsafe(32)` — 43 chars
of URL-safe base64 (~256 bits of entropy). Plaintext in DB: the cookie
itself is the secret and never leaves HTTPS+HttpOnly.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.core.time import utc_now
from app.db.models import AdminSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def public_id(session_id: str) -> str:
    """The handle the console lists and revokes a session by.

    Never the session id itself: that is the cookie, and returning it as JSON
    or taking it in a URL hands it to page script and to the access log.
    """
    return hashlib.sha256(session_id.encode()).hexdigest()[:32]


async def create_session(
    session: AsyncSession,
    *,
    user_id: int,
    ttl_days: int,
    user_agent: str | None,
    ip: str | None,
) -> AdminSession:
    now = utc_now()
    row = AdminSession(
        session_id=new_session_id(),
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + datetime.timedelta(days=ttl_days),
        user_agent=user_agent,
        ip=ip,
    )
    session.add(row)
    await session.commit()
    return row


async def load_valid_session(session: AsyncSession, session_id: str) -> AdminSession | None:
    """Return the row if present and not expired, else None. Bumps ``last_seen_at``."""
    row = (
        await session.execute(select(AdminSession).where(AdminSession.session_id == session_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    now = utc_now()
    if row.expires_at <= now:
        await session.delete(row)
        await session.commit()
        return None
    row.last_seen_at = now
    await session.commit()
    return row


async def revoke_session(session: AsyncSession, session_id: str) -> bool:
    row = (
        await session.execute(select(AdminSession).where(AdminSession.session_id == session_id))
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def purge_expired(session: AsyncSession) -> int:
    now = utc_now()
    result = await session.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    await session.commit()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
