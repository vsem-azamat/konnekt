"""One log line per request, and the id that finds it again.

Every line written while the request is handled carries `request_id`, and the
caller gets it back in `X-Request-Id`, so "it failed at 14:03" becomes one
query. The line names the route by its template and never carries the query
string: a sign-in callback's `code` and `state` are in it.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import TYPE_CHECKING

import structlog

from app.core.logging import get_logger

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = get_logger("webapi.request")

# The container check, every 30 s for as long as it runs.
QUIET_PATHS = frozenset({"/api/health"})

# What a caller may supply: long enough to be unique, short and plain enough to
# be safe in a log line and a header.
_WELL_FORMED = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestLog:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sent = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = sent if _WELL_FORMED.match(sent) else uuid.uuid4().hex
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                self._log(scope, 500, started, failed=True)
                raise
            self._log(scope, status, started)

    @staticmethod
    def _log(scope: Scope, status: int, started: float, *, failed: bool = False) -> None:
        path = scope["path"]
        if path in QUIET_PATHS and not failed and status < 400:
            return
        route = getattr(scope.get("route"), "path", None)
        fields = {
            "method": scope["method"],
            "path": path,
            "route": route,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if failed:
            logger.error("http_request", exc_info=True, **fields)
        elif status >= 500:
            logger.error("http_request", **fields)
        elif status >= 400:
            logger.warning("http_request", **fields)
        else:
            logger.info("http_request", **fields)
