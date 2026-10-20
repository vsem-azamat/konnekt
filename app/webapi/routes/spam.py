"""The console's ads queue: what the detector caught, and the moderator's answer."""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.webapi.deps import get_session, require_super_admin
from app.webapi.schemas import SpamPingRead, SpamQueueCount, SpamReviewRequest
from app.webapi.services.spam_pings import AlreadyAnsweredError, PingStatus, count_unreviewed, read_pings, review_ping

router = APIRouter(prefix="/spam", tags=["spam"])


@router.get("/pings", response_model=list[SpamPingRead])
async def list_pings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
    chat_id: Annotated[int | None, Query(description="Filter by chat_id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Max rows to return")] = 100,
    status: Annotated[PingStatus, Query(description="all, the unanswered queue, or false alarms")] = "all",
    days: Annotated[int | None, Query(ge=1, le=366, description="Only the last N days")] = None,
    before_at: Annotated[datetime.datetime | None, Query(description="The last hit's detected_at")] = None,
    before_id: Annotated[int | None, Query(description="The last hit's id")] = None,
) -> list[SpamPingRead]:
    """Ad-detector hits, newest first, filtered as the console asks; a page
    goes on after the hit named by ``before_at`` and ``before_id``."""
    if (before_at is None) != (before_id is None):
        raise HTTPException(status_code=422, detail="before_at and before_id go together")
    before = None
    if before_at is not None and before_id is not None:
        # Stored as naive UTC, which is also how the list writes it out.
        if before_at.tzinfo is not None:
            before_at = before_at.astimezone(datetime.UTC).replace(tzinfo=None)
        before = (before_at, before_id)
    return await read_pings(session, chat_id=chat_id, limit=limit, status=status, days=days, before=before)


@router.get("/pings/unreviewed", response_model=SpamQueueCount)
async def count_queue(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
    chat_id: Annotated[int | None, Query(description="Filter by chat_id")] = None,
    days: Annotated[int | None, Query(ge=1, le=366, description="Only the last N days")] = None,
) -> SpamQueueCount:
    """How many hits wait in the queue under these filters."""
    return SpamQueueCount(count=await count_unreviewed(session, chat_id=chat_id, days=days))


@router.post("/pings/{ping_id}/review", response_model=SpamPingRead)
async def review(
    ping_id: int,
    payload: SpamReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> SpamPingRead:
    """Answers a hit, which takes it out of the queue; 409 with the hit as it
    is when somebody answered it first."""
    try:
        ping = await review_ping(session, ping_id, payload.verdict, admin_id=admin_id)
    except AlreadyAnsweredError as answered:
        raise HTTPException(status_code=409, detail=answered.ping.model_dump(mode="json")) from answered
    if ping is None:
        raise HTTPException(status_code=404, detail=f"Spam ping {ping_id} not found")
    return ping
