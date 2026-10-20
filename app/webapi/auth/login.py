"""Opening a console session once a door has decided who is asking."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from app.core.config import settings
from app.webapi.auth import session_store

if TYPE_CHECKING:
    from fastapi import Request, Response
    from sqlalchemy.ext.asyncio import AsyncSession


async def open_session(session: AsyncSession, request: Request, response: Response, *, user_id: int) -> None:
    """Record the session and put its token in the response's cookie.

    The caller has already checked the person against the super-admin list: a
    door decides identity, this only issues the session.
    """
    _row, token = await session_store.create_session(
        session,
        user_id=user_id,
        ttl_days=settings.webapi.session_ttl_days,
        user_agent=request.headers.get("user-agent"),
        ip=caller_address(request),
    )
    response.set_cookie(
        key=settings.webapi.session_cookie_name,
        value=token,
        max_age=settings.webapi.session_ttl_days * 86400,
        secure=settings.webapi.session_cookie_secure,
        httponly=True,
        samesite=settings.webapi.session_cookie_samesite,
        path="/",
    )


def caller_address(request: Request) -> str | None:
    """The caller's address if it is one: it arrives through forwarded headers."""
    host = request.client.host if request.client else None
    if host and "%" in host:
        return None  # an IPv6 zone, of any length, says nothing about who
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None
