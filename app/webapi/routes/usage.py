"""The console's «Использование» and «Источники»: how the Mini App is used, and where the site's visitors come from.

Read only, and only for the console. The writes are `POST /api/public/events`
(app/webapi/routes/events.py) and the daily import (app/usage/sources.py).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.usage import report, sources
from app.webapi.deps import get_session
from app.webapi.schemas import Sources, Usage

router = APIRouter(prefix="/usage", tags=["usage"])

SOURCE_PERIODS = (7, 30, 90)


@router.get("", response_model=Usage)
async def usage(session: Annotated[AsyncSession, Depends(get_session)], days: int = 7) -> Usage:
    if days not in report.PERIODS:
        raise HTTPException(status_code=422, detail="bad_period")
    return Usage.model_validate(await report.usage(session, days=days, now=utc_now()))


@router.get("/sources", response_model=Sources)
async def usage_sources(session: Annotated[AsyncSession, Depends(get_session)], days: int = 30) -> Sources:
    if days not in SOURCE_PERIODS:
        raise HTTPException(status_code=422, detail="bad_period")
    return Sources.model_validate(await sources.report(session, days=days, today=utc_now().date()))
