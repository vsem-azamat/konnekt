"""Sign in from a browser with Telegram OpenID Connect.

A second door beside the Mini App's `initData` (`auth.py`), added by choice and
with a different proof: not a signature the bot token can check, but an
`id_token` Telegram signed for this client and `app.webapi.auth.telegram_oidc`
verifies against Telegram's published keys. The same super-admin list decides
who gets a session afterwards; being known to Telegram is not being allowed in.

The flow's secrets (state, nonce, PKCE verifier) wait in an httpOnly `__Host-`
cookie: Secure, no Domain and Path=/, which is what keeps another host under the
same domain from planting a flow of its own. A callback without the cookie of
the browser that started it is refused, which is what stops somebody else's
valid code from signing the admin's browser in to their account.
"""

from __future__ import annotations

import ipaddress
import time
from collections import deque
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.auth import telegram_oidc
from app.webapi.auth.login import caller_address, open_session
from app.webapi.deps import get_session

logger = get_logger("webapi.auth.telegram")
router = APIRouter(prefix="/auth/telegram", tags=["auth"])

_FLOW_TTL_SECONDS = 600
CALLBACKS_PER_MINUTE = 10
# Per process, like the throttles beside it; a forgotten entry only lets one more attempt through.
_callbacks: dict[str, deque[float]] = {}
_REMEMBERED = 10_000
_http: httpx.AsyncClient | None = None


def forget() -> None:
    """For tests: nobody has called back recently."""
    _callbacks.clear()


async def get_oidc_http() -> httpx.AsyncClient:
    """The process's one client to Telegram, made on first use and closed with the app."""
    global _http  # noqa: PLW0603
    if _http is None:
        _http = httpx.AsyncClient(timeout=10)
    return _http


async def close_oidc_http() -> None:
    global _http  # noqa: PLW0603
    client, _http = _http, None
    if client is not None:
        await client.aclose()


def _flow_cookie() -> str:
    # `__Host-` is only honoured over https; local http development gets the bare name.
    return "__Host-konnekt_oidc_flow" if settings.webapi.session_cookie_secure else "konnekt_oidc_flow"


def _limit_key(request: Request) -> str:
    """Who an attempt is counted against: an IPv4 address, or an IPv6 /64.

    A /64 is what one subscriber is given; counting single addresses would
    leave them 2**64 allowances.
    """
    address = caller_address(request)
    if address is None:
        return "unknown"
    ip = ipaddress.ip_address(address)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else address


def _limited(request: Request) -> bool:
    now = time.monotonic()
    key = _limit_key(request)
    # Re-inserted on every use, so the first key in the table is the one least recently seen.
    recent = _callbacks.pop(key, None) or deque()
    _callbacks[key] = recent
    while len(_callbacks) > _REMEMBERED:
        del _callbacks[next(iter(_callbacks))]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= CALLBACKS_PER_MINUTE:
        return True
    recent.append(now)
    return False


def _require_enabled() -> None:
    if not settings.webapi.oidc_enabled:
        raise HTTPException(status_code=404)


def _redirect_uri() -> str:
    return f"{settings.webapi.admin_url.rstrip('/')}/api/auth/telegram/callback"


def _back(path: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.webapi.admin_url.rstrip('/')}{path}", status_code=302)
    response.delete_cookie(_flow_cookie(), path="/", secure=settings.webapi.session_cookie_secure, httponly=True)
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
        key=_flow_cookie(),
        value=f"{flow.state}.{flow.nonce}.{flow.verifier}",
        max_age=_FLOW_TTL_SECONDS,
        secure=settings.webapi.session_cookie_secure,
        httponly=True,
        # Lax so the cookie comes back with the redirect from Telegram.
        samesite="lax",
        path="/",
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
    if _limited(request):
        raise HTTPException(status_code=429, detail="too many attempts")
    parts = request.cookies.get(_flow_cookie(), "").split(".")
    if len(parts) != 3 or not all(parts):
        return _failed("no sign-in in progress in this browser")
    expected_state, nonce, verifier = parts
    if not state or not telegram_oidc.constant_time_equal(state, expected_state):
        return _failed("state mismatch")
    if error or not code:
        # `error` is whatever the caller put in the URL.
        return _failed(f"telegram returned {(error or 'no code')[:64]!r}")

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
