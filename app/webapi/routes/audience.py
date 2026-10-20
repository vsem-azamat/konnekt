"""The console's Audience page: who has used our bots or the Mini App.

Read only. Nothing here writes to anyone: announcements do not exist yet.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audience import views
from app.core.enums import Touchpoint
from app.core.time import utc_now
from app.webapi.deps import get_session
from app.webapi.schemas import AudiencePage, AudiencePersonRead, AudienceStatus, AudienceSummary

router = APIRouter(prefix="/audience", tags=["audience"])


@router.get("/summary", response_model=AudienceSummary)
async def audience_summary(session: Annotated[AsyncSession, Depends(get_session)]) -> AudienceSummary:
    return AudienceSummary.model_validate(await views.summary(session, now=utc_now()))


@router.get("", response_model=AudiencePage)
async def audience_page(
    session: Annotated[AsyncSession, Depends(get_session)],
    touchpoint: Touchpoint | None = None,
    status: AudienceStatus | None = None,
    language: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    new_days: Annotated[int | None, Query(ge=1, le=365)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
) -> AudiencePage:
    after = views.parse_cursor(cursor) if cursor else None
    if cursor and after is None:
        raise HTTPException(status_code=422, detail="bad_cursor")
    return AudiencePage.model_validate(
        await views.page(
            session,
            now=utc_now(),
            touchpoint=touchpoint,
            status=status,
            language=language,
            query=q,
            new_days=new_days,
            limit=limit,
            after=after,
        )
    )


@router.get("/{user_id}", response_model=AudiencePersonRead)
async def audience_person(user_id: int, session: Annotated[AsyncSession, Depends(get_session)]) -> AudiencePersonRead:
    """Declared after `/summary`, which this route would otherwise take for an id."""
    card = await views.person(session, user_id)
    if card is None:
        raise HTTPException(status_code=404, detail="not_in_audience")
    return AudiencePersonRead.model_validate(card)
