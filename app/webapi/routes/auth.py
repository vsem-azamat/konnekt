"""Authentication: a Telegram Mini App session, and nothing else.

There used to be two other doors. The Login Widget asked a browser to prove an
identity Telegram had already proven, and magic links mailed a bearer token
through a chat — a link that signs in without a password, forwardable by
anyone who receives it, and which in production was never once used.

`initData` removes the question. Telegram signs it with the bot's own token
before the page loads, so the caller is attested before the first request
rather than by it, and there is no secret in flight that means anything to
whoever else might read it.

The cost, stated plainly because it is permanent: the console opens only from
inside a Telegram client. Telegram Desktop counts, so a laptop still works.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.auth import session_store
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session, require_super_admin
from app.webapi.schemas import AuthMeResponse, WebAppLoginPayload

logger = get_logger("webapi.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/webapp")
async def webapp_login(
    payload: WebAppLoginPayload,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthMeResponse:
    """Exchange a signed `initData` payload for a session cookie."""
    try:
        caller = verify_init_data(payload.init_data, bot_token=settings.telegram.token)
    except InitDataError as err:
        # Which check failed is useful to somebody probing this and useless to
        # a real client, whose payload Telegram itself assembled.
        logger.warning("webapp_login_rejected", reason=str(err))
        raise HTTPException(status_code=401, detail="login failed") from err

    if caller.user_id not in settings.admin.super_admins:
        logger.warning("webapp_login_not_authorized", user_id=caller.user_id)
        raise HTTPException(status_code=403, detail="not authorized")

    _row, token = await session_store.create_session(
        session,
        user_id=caller.user_id,
        ttl_days=settings.webapi.session_ttl_days,
        user_agent=request.headers.get("user-agent"),
        ip=_address(request),
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
    return AuthMeResponse(user_id=caller.user_id)


@router.get("/me")
async def me(user_id: Annotated[int, Depends(require_super_admin)]) -> AuthMeResponse:
    return AuthMeResponse(user_id=user_id)


def _address(request: Request) -> str | None:
    """The caller's address if it is one: it arrives through forwarded headers."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """End the session this browser holds, and its cookie.

    Open to anybody: signing out without a session is a no-op, and a cookie
    that could not be ended from the device holding it lasted its 30 days.
    """
    token = request.cookies.get(settings.webapi.session_cookie_name)
    if token:
        await session_store.end_session(session, token)
    response.delete_cookie(
        key=settings.webapi.session_cookie_name,
        path="/",
        secure=settings.webapi.session_cookie_secure,
        httponly=True,
        samesite=settings.webapi.session_cookie_samesite,
    )
