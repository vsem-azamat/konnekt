"""Sign in from a browser with Telegram OpenID Connect.

A second door beside the Mini App's `initData` (`auth.py`), added by choice and
with a different proof: not a signature the bot token can check, but an
`id_token` Telegram signed for this client and `app.webapi.auth.telegram_oidc`
verifies against Telegram's published keys. The same super-admin list decides
who gets a session afterwards; being known to Telegram is not being allowed in.

The flow's secrets (state, nonce, PKCE verifier) wait in an httpOnly cookie
scoped to these two routes. A callback without the cookie of the browser that
started it is refused, which is what stops somebody else's valid code from
signing the admin's browser in to their account.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.auth import telegram_oidc
from app.webapi.auth.login import open_session
from app.webapi.deps import get_session

logger = get_logger("webapi.auth.telegram")
router = APIRouter(prefix="/auth/telegram", tags=["auth"])

_FLOW_COOKIE = "konnekt_oidc_flow"
_FLOW_PATH = "/api/auth/telegram"
_FLOW_TTL_SECONDS = 600


async def get_oidc_http() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(timeout=10) as http:
        yield http


def _require_enabled() -> None:
    if not settings.webapi.oidc_enabled:
        raise HTTPException(status_code=404)


def _redirect_uri() -> str:
    return f"{settings.webapi.admin_url.rstrip('/')}{_FLOW_PATH}/callback"


def _back(path: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.webapi.admin_url.rstrip('/')}{path}", status_code=302)
    response.delete_cookie(_FLOW_COOKIE, path=_FLOW_PATH)
    return response


def _failed(reason: str, error: str = "failed") -> RedirectResponse:
    # Which check failed is for the log; the page only needs to say it did.
    logger.warning("telegram_login_rejected", reason=reason)
    return _back(f"/login?error={error}")


@router.get("/login", dependencies=[Depends(_require_enabled)])
async def login() -> RedirectResponse:
    flow = telegram_oidc.start(client_id=settings.webapi.oidc_client_id, redirect_uri=_redirect_uri())
    response = RedirectResponse(flow.url, status_code=302)
    response.set_cookie(
        key=_FLOW_COOKIE,
        value=f"{flow.state}.{flow.nonce}.{flow.verifier}",
        max_age=_FLOW_TTL_SECONDS,
        secure=settings.webapi.session_cookie_secure,
        httponly=True,
        # Lax so the cookie comes back with the redirect from Telegram.
        samesite="lax",
        path=_FLOW_PATH,
    )
    return response


@router.get("/callback", dependencies=[Depends(_require_enabled)])
async def callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    http: Annotated[httpx.AsyncClient, Depends(get_oidc_http)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    parts = request.cookies.get(_FLOW_COOKIE, "").split(".")
    if len(parts) != 3:
        return _failed("no sign-in in progress in this browser")
    expected_state, nonce, verifier = parts
    if not state or not hmac.compare_digest(state, expected_state):
        return _failed("state mismatch")
    if error or not code:
        return _failed(f"telegram returned {error or 'no code'}")

    try:
        user_id = await telegram_oidc.complete(
            http,
            code=code,
            verifier=verifier,
            nonce=nonce,
            client_id=settings.webapi.oidc_client_id,
            client_secret=settings.webapi.oidc_client_secret,
            redirect_uri=_redirect_uri(),
        )
    except telegram_oidc.OidcError as err:
        return _failed(str(err))

    if user_id not in settings.admin.super_admins:
        return _failed("not a super admin", error="not_admin")

    response = _back("/console")
    await open_session(session, request, response, user_id=user_id)
    return response
