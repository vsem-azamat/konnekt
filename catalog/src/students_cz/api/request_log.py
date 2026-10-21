"""One log line per request, and the id that finds it again.

Every line written while the request is handled carries `request_id`, and the
caller gets it back in `X-Request-Id`: "it failed at 14:03" becomes one query.
The line names the route by its template and never carries the query string.
"""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from students_cz.core.logs import bound

log = logging.getLogger("students_cz.request")

# The container check, every 15 s for as long as it runs.
QUIET_PATHS = frozenset({"/healthz"})

# What a caller may supply: long enough to be unique, short and plain enough to
# be safe in a log line and a header.
_WELL_FORMED = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def route_template(scope: Scope) -> str | None:
    """`/api/v1/requests/{request_id}` for `/api/v1/requests/7`; `None` if no route.

    FastAPI keeps a route's own path (`/requests/{request_id}`) without the
    prefixes of the routers it was included through, so the template is
    rebuilt from the request's path and the parameters it matched. A path that
    no route took has none, which keeps a scanner's guesses from becoming
    values to search on.
    """
    if scope.get("route") is None:
        return None
    segments = scope["path"].split("/")
    at = 0
    for name, value in scope.get("path_params", {}).items():
        for i in range(at, len(segments)):
            if segments[i] == str(value):
                segments[i] = "{" + name + "}"
                at = i + 1
                break
    return "/".join(segments)


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
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        with bound(request_id=request_id):
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
        fields = {
            "method": scope["method"],
            "path": path,
            "route": route_template(scope),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        level = (
            logging.ERROR
            if status >= 500
            else logging.WARNING
            if status >= 400
            else logging.INFO
        )
        log.log(level, "http_request", exc_info=failed, extra={"fields": fields})
