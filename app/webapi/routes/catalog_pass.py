"""The Mini App endpoint that notes a tap on a catalog chat's join button.

Its credential is Telegram's signature over ``initData``, as for the join
check. The tap proves the account is somebody's own client, which is what the
captcha asks; the pass it leaves is spent by the join request that follows
(``app/captcha/service.py``).

The chat is named by its public link, which is what the catalog hands out: its
id is not part of the public catalog and does not need to be. Every refusal is
the same 403 with no detail, an unknown or unmanaged chat included.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import CatalogPass, Chat
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session

logger = get_logger("webapi.catalog_pass")

router = APIRouter(prefix="/public", tags=["public"])

_REFUSED = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="pass_refused")


class CatalogPassRequest(BaseModel):
    init_data: str = Field(description="Raw Telegram.WebApp.initData string")
    link: str = Field(max_length=256, description="The chat's public link, as the catalog lists it")


class CatalogPassResult(BaseModel):
    status: str


@router.post("/catalog-pass", response_model=CatalogPassResult)
async def note_catalog_tap(
    payload: CatalogPassRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogPassResult:
    """Let the caller's next join request to this chat in without a captcha."""
    try:
        caller = verify_init_data(payload.init_data, bot_token=settings.telegram.token)
    except InitDataError:
        logger.info("catalog_pass_signature_refused")
        raise _REFUSED from None

    hours = settings.captcha.catalog_pass_hours
    chat_id = await session.scalar(
        select(Chat.id).where(
            Chat.public_link == payload.link,
            Chat.resource_status == Chat.STATUS_APPROVED,
            Chat.join_mode == Chat.JOIN_CAPTCHA,
        )
    )
    if hours == 0 or chat_id is None:
        logger.info("catalog_pass_unavailable", user_id=caller.user_id)
        raise _REFUSED

    expires_at = utc_now() + datetime.timedelta(hours=hours)
    # Tapping again renews the one pass rather than adding another. Two taps
    # at once may both try to insert; the one that lost has nothing to add.
    await session.merge(CatalogPass(user_id=caller.user_id, chat_id=chat_id, expires_at=expires_at))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
    logger.info("catalog_pass_noted", chat_id=chat_id, user_id=caller.user_id)
    return CatalogPassResult(status="noted")
