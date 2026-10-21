"""The Mini App reporting its own failures, so nobody has to report them for it.

A public endpoint that writes (docs/invariants.md), though only a log line and
a counter: `client_error` at warning, which reaches Loki without becoming an
alert in the report chat, and `mini_app_client_errors_total` by kind and
platform, which is what Grafana alerts on.

Signed like `/seen`, so that only a Telegram launch can fill the log, but the
signature is used for nothing else. The line carries what failed and where —
the screen's route pattern, the endpoint, the status, the build — and nothing
about who: no id, no name, no initData. The id Telegram signed lives here only
as a key of the per-person limit, in this process's memory.

Bounded three ways: the body before it is parsed, each field by the schema, and
the number of lines, per person and for everybody together. What the limits
turn away is answered like the rest and counted in
`mini_app_client_errors_dropped_total`, so a flood shows as a flood.
"""

from __future__ import annotations

import re
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError

from app.core import metrics
from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data

logger = get_logger("webapi.client_errors")

router = APIRouter(prefix="/public", tags=["public"])

# A day, as the catalog allows: the app stays open as long as somebody leaves
# it, and the failure worth hearing about is often the one after hours away.
MAX_AGE_SECONDS = 24 * 3600
MAX_BODY_BYTES = 64 * 1024
WINDOW_SECONDS = 600.0
# Lines per window: one person's, and everybody's together.
PER_PERSON = 30
OVERALL = 1000

# Where the client may run, as Telegram names it; anything else is `other`, so
# a client cannot mint a series.
PLATFORMS = frozenset({"android", "android_x", "ios", "macos", "tdesktop", "unigram", "web", "weba", "webk"})

# A route pattern or an endpoint, never a whole address: no host, no query.
_PATH = r"^/[A-Za-z0-9/_:.{}*\-]{0,119}$"
_BUILD_WORD = r"^[A-Za-z0-9._+-]{1,40}$"

Kind = Literal["error", "unhandled_rejection", "render", "api", "empty", "layout"]


class ClientEvent(BaseModel):
    kind: Kind
    message: str = Field(default="", max_length=500)
    stack: str = Field(default="", max_length=2000)
    route: Annotated[str, Field(pattern=_PATH)]
    endpoint: Annotated[str, Field(pattern=_PATH)] | None = None
    status: Annotated[int, Field(ge=0, le=599)] | None = None


class ClientErrorReport(BaseModel):
    init_data: str = Field(max_length=4096)
    version: Annotated[str, Field(pattern=_BUILD_WORD)]
    platform: str = Field(max_length=20)
    tg_version: Annotated[str, Field(pattern=_BUILD_WORD)]
    events: list[ClientEvent] = Field(min_length=1, max_length=20)


# Per process, as the throttles in the bot are. Fixed windows: a forgotten
# entry only lets a few more lines through.
_window_started = 0.0
_overall = 0
_per_person: dict[int, int] = {}


def forget() -> None:
    """For tests: start a fresh window."""
    global _window_started, _overall
    _window_started, _overall = 0.0, 0
    _per_person.clear()


def _admit(person: int, wanted: int) -> tuple[int, int, int]:
    """How many of `wanted` lines to write, and how many each limit turned away."""
    global _window_started, _overall
    now = time.monotonic()
    if now - _window_started >= WINDOW_SECONDS:
        forget()
        _window_started = now
    mine = _per_person.get(person, 0)
    by_person = min(wanted, max(PER_PERSON - mine, 0))
    admitted = min(by_person, max(OVERALL - _overall, 0))
    _per_person[person] = mine + admitted
    _overall += admitted
    return admitted, wanted - by_person, by_person - admitted


# The query and fragment of any address: the Mini App's own carries initData
# in its fragment, and a query can carry anything.
_ADDRESS_TAIL = re.compile(r"(https?://[^\s?#]*)[?#]\S*")
# Telegram ids, and any other number long enough to name somebody.
_LONG_NUMBER = re.compile(r"\d{6,}")


def _scrub(text: str) -> str:
    return _LONG_NUMBER.sub("…", _ADDRESS_TAIL.sub(r"\1", text))


async def _read_capped(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="too_large")
    return bytes(body)


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT)
async def client_errors(request: Request) -> Response:
    """Log and count what failed in the caller's Mini App."""
    try:
        report = ClientErrorReport.model_validate_json(await _read_capped(request))
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from None
    try:
        caller = verify_init_data(report.init_data, bot_token=settings.telegram.token, max_age_seconds=MAX_AGE_SECONDS)
    except InitDataError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="check_failed") from None

    admitted, by_person, overall = _admit(caller.user_id, len(report.events))
    if by_person:
        metrics.CLIENT_ERRORS_DROPPED.labels(reason="rate_limited").inc(by_person)
    if overall:
        metrics.CLIENT_ERRORS_DROPPED.labels(reason="overall_limit").inc(overall)

    platform = report.platform if report.platform in PLATFORMS else "other"
    for event in report.events[:admitted]:
        metrics.CLIENT_ERRORS.labels(kind=event.kind, platform=platform).inc()
        logger.warning(
            "client_error",
            kind=event.kind,
            message=_scrub(event.message),
            stack=_scrub(event.stack),
            route=event.route,
            endpoint=event.endpoint,
            status=event.status,
            version=report.version,
            platform=platform,
            tg_version=report.tg_version,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
