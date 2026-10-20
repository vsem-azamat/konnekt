"""The console's ads queue: what the detector caught, and the moderator's answer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.webapi.deps import get_session, require_super_admin
from app.webapi.schemas import SpamPingRead, SpamReviewRequest
from app.webapi.services.spam_pings import PingStatus, read_pings, review_ping

router = APIRouter(prefix="/spam", tags=["spam"])


@router.get("/pings", response_model=list[SpamPingRead])
async def list_pings(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
    chat_id: Annotated[int | None, Query(description="Filter by chat_id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Max rows to return")] = 100,
    status: Annotated[PingStatus, Query(description="all, the unanswered queue, or false alarms")] = "all",
    days: Annotated[int | None, Query(ge=1, le=366, description="Only the last N days")] = None,
    before_id: Annotated[int | None, Query(description="Continue after this hit")] = None,
) -> list[SpamPingRead]:
    """Ad-detector hits, newest first, filtered as the console asks."""
    return await read_pings(session, chat_id=chat_id, limit=limit, status=status, days=days, before_id=before_id)


@router.post("/pings/{ping_id}/review", response_model=SpamPingRead)
async def review(
    ping_id: int,
    payload: SpamReviewRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> SpamPingRead:
    """Answers a hit, which takes it out of the queue."""
    ping = await review_ping(session, ping_id, payload.verdict, admin_id=admin_id)
    if ping is None:
        raise HTTPException(status_code=404, detail=f"Spam ping {ping_id} not found")
    return ping
