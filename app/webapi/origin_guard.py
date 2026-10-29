"""Writes that carry the console's cookie must come from one of our pages.

`SameSite=Lax` keeps the cookie off other *sites*, but a host under the same
registrable domain is the same site and still sends it. Such a page can post a
`text/plain` body (no CORS preflight) that the API reads as JSON. A browser
always names the page's origin on a write, so a cookie-bearing write with no
origin, a `null` one, or one that is not ours is refused.

Writes without the cookie are left alone: nothing rides along to be abused, and
the endpoint's own proof (a signed `initData`) decides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

# What the CORS middleware falls back to when no URL is configured: the Vite
# dev server, which serves over https (web/vite.config.ts).
DEV_ORIGIN = "https://localhost:5173"
_WRITES = {"POST", "PUT", "PATCH", "DELETE"}


class RequireOurOrigin:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _WRITES:
            request = Request(scope)
            if settings.webapi.session_cookie_name in request.cookies:
                allowed = settings.webapi.allowed_origins or [DEV_ORIGIN]
                if request.headers.get("origin") not in allowed:
                    await JSONResponse({"detail": "origin not allowed"}, status_code=403)(scope, receive, send)
                    return
        await self.app(scope, receive, send)
