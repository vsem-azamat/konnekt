"""What people do in the Mini App, for the console's «Использование».

A public endpoint that writes (docs/invariants.md), signed like `/seen`: the
person is the id Telegram signed, never one the body names. Every event is one
of the list in app/usage/events.py with properties of our own words, so
nothing a person typed can arrive here.

Bounded like the error reports: the body before it is parsed, each event by
the schema, and the events per person and for everybody together in a
window. What the limits turn away is answered like the rest and counted in
`mini_app_events_dropped_total`; so is an event this server cannot read, which
is skipped rather than failing the batch. Somebody who turned counting off in
the app sends nothing; the app keeps that choice (web/src/lib/track.ts).
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audience.record import SOURCE
from app.core import metrics
from app.core.config import settings
from app.core.time import utc_now
from app.usage import record
from app.usage.events import Event
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session
from app.webapi.routes.client_errors import MAX_AGE_SECONDS, PLATFORMS

router = APIRouter(prefix="/public", tags=["public"])

MAX_BODY_BYTES = 64 * 1024
PER_BATCH = 50
WINDOW_SECONDS = 600.0
# Events per window. One person on screen for the whole window sends 20
# heartbeats; the rest is room for a busy few minutes of tapping.
PER_PERSON = 200
OVERALL = 20_000

_BUILD_WORD = r"^[A-Za-z0-9._+-]{1,40}$"

for _reason in ("invalid", "rate_limited", "overall_limit"):
    metrics.EVENTS_DROPPED.labels(reason=_reason)


class EventBatch(BaseModel):
    init_data: str = Field(max_length=4096)
    version: Annotated[str, Field(pattern=_BUILD_WORD)]
    platform: str = Field(max_length=20)
    # Checked one by one below, so one event a newer client added does not lose the rest.
    events: list[dict[str, Any]] = Field(min_length=1, max_length=PER_BATCH)


_window_started = 0.0
_overall = 0
_per_person: dict[int, int] = {}


def forget() -> None:
    """For tests: start a fresh window."""
    global _window_started, _overall
    _window_started, _overall = 0.0, 0
    _per_person.clear()


def _admit(person: int, wanted: int) -> tuple[int, int, int]:
    """How many of `wanted` events to keep, and how many each limit turned away."""
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


def _valid(events: list[dict[str, Any]]) -> list[Event]:
    valid = []
    for raw in events:
        try:
            valid.append(Event.model_validate(raw))
        except ValidationError:
            metrics.EVENTS_DROPPED.labels(reason="invalid").inc()
    return valid


async def _read_capped(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="too_large")
    return bytes(body)


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
async def events(request: Request, session: Annotated[AsyncSession, Depends(get_session)]) -> Response:
    """Write what the caller did in the Mini App."""
    try:
        batch = EventBatch.model_validate_json(await _read_capped(request))
    except ValidationError as error:
        # Without the input: for a body that is not JSON that is all of it, initData included.
        raise RequestValidationError(error.errors(include_input=False)) from None
    try:
        caller = verify_init_data(batch.init_data, bot_token=settings.telegram.token, max_age_seconds=MAX_AGE_SECONDS)
    except InitDataError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="check_failed") from None

    valid = _valid(batch.events)
    admitted, by_person, overall = _admit(caller.user_id, len(valid))
    if by_person:
        metrics.EVENTS_DROPPED.labels(reason="rate_limited").inc(by_person)
    if overall:
        metrics.EVENTS_DROPPED.labels(reason="overall_limit").inc(overall)
    if not admitted:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    source = caller.start_param if caller.start_param and SOURCE.fullmatch(caller.start_param) else None
    record.write(
        session,
        user_id=caller.user_id,
        events=valid[:admitted],
        platform=batch.platform if batch.platform in PLATFORMS else "other",
        version=batch.version,
        source=source,
        now=utc_now(),
    )
    await session.commit()
    metrics.EVENTS.inc(admitted)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
