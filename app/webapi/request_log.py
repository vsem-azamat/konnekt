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


def route_template(scope: Scope) -> str | None:
    """`/api/chats/{chat_id}` for `/api/chats/-100`; `None` if no route took it.

    FastAPI keeps a route's own path (`/{chat_id}`) without the prefixes of the
    routers it was included through. The route is the tail of the request's
    path, so the prefix is what comes before that tail. A path no route took
    has none, which keeps a scanner's guesses from becoming values to search on.
    """
    route = scope.get("route")
    if route is None:
        return None
    segments = scope["path"].split("/")
    template = str(getattr(route, "path", "") or "")
    tail = template.count("/")
    if template and tail <= len(segments) - 1 and ":" not in template:
        return "/".join(segments[: len(segments) - tail]) + template
    # A path converter swallows slashes, so the tail's length is not known:
    # name the matched parameters in place instead.
    at = 0
    for name, value in scope.get("path_params", {}).items():
        for i in range(at, len(segments)):
            if segments[i] == str(value):
                segments[i] = "{" + name + "}"
                at = i + 1
                break
    return "/".join(segments)


class RequestLog:
    """Outside FastAPI's server-error middleware, so a 500 is logged once, here.

    Inside it, an unhandled error is answered without the id and then raised
    again to uvicorn, which logs it a second time: two lines and two alerts for
    one failure.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sent = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = sent if _WELL_FORMED.match(sent) else uuid.uuid4().hex
        status = 500
        answered = False
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status, answered
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                answered = True
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                self._log(scope, status, started, failed=True)
                if not answered:
                    raise
                # The error middleware has answered 500 and re-raised for the
                # server to report; the report is this line.
            else:
                self._log(scope, status, started)

    @staticmethod
    def _log(scope: Scope, status: int, started: float, *, failed: bool = False) -> None:
        path = scope["path"]
        if path in QUIET_PATHS and not failed and status < 400:
            return
        # The route, never the path: a path carries the ids of the people it
        # is about (/api/audience/<id>), and the logs keep those out.
        fields = {
            "method": scope["method"],
            "route": route_template(scope),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if failed:
            logger.error("http_request", exc_info=True, **fields)
        elif status == 500:
            logger.error("http_request", **fields)
        elif status >= 400:
            # 502 and 503 are answers the API gives on purpose (the catalog is
            # not connected, Telegram is unreachable): worth a line, not an alert.
            logger.warning("http_request", **fields)
        else:
            logger.info("http_request", **fields)
