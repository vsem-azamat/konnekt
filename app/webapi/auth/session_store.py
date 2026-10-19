"""CRUD for ``admin_sessions``.

A session's token is :func:`secrets.token_urlsafe(32)`, ~256 bits, and lives
in the HttpOnly cookie alone. The table keeps its SHA-256 in ``session_id``:
a copy of the table, a backup or a careless query is then not a list of
working console sessions. Unsalted is enough for a random 256-bit token.
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


# last_seen_at is for a person reading the session list; writing it on every
# request committed a row per click.
_SEEN_EVERY = datetime.timedelta(minutes=5)


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def digest(token: str) -> str:
    """What the table keeps for a cookie's token."""
    return hashlib.sha256(token.encode()).hexdigest()


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
) -> tuple[AdminSession, str]:
    """The new row and the token for the cookie, which is stored nowhere else."""
    now = utc_now()
    token = new_session_id()
    row = AdminSession(
        session_id=digest(token),
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + datetime.timedelta(days=ttl_days),
        user_agent=user_agent,
        ip=ip,
    )
    session.add(row)
    await session.commit()
    return row, token


async def load_valid_session(session: AsyncSession, token: str) -> AdminSession | None:
    """The row for a cookie's token if present and not expired, else None."""
    row = (
        await session.execute(select(AdminSession).where(AdminSession.session_id == digest(token)))
    ).scalar_one_or_none()
    if row is None:
        return None
    now = utc_now()
    if row.expires_at <= now:
        await session.delete(row)
        await session.commit()
        return None
    if now - row.last_seen_at >= _SEEN_EVERY:
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


async def end_session(session: AsyncSession, token: str) -> None:
    """Sign out the session a cookie holds; nothing if it holds none."""
    await session.execute(delete(AdminSession).where(AdminSession.session_id == digest(token)))
    await session.commit()


async def purge_expired(session: AsyncSession) -> int:
    now = utc_now()
    result = await session.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    await session.commit()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
