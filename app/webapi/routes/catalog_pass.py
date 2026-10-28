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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import CatalogPass, Chat
from app.db.upsert import insert_for
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session

logger = get_logger("webapi.catalog_pass")

router = APIRouter(prefix="/public", tags=["public"])

# The tap can come long after the launch: the Mini App keeps one initData for
# the whole visit, and the catalog accepts it for a day.
_LAUNCH_MAX_AGE_SECONDS = 86_400

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
        caller = verify_init_data(
            payload.init_data, bot_token=settings.telegram.token, max_age_seconds=_LAUNCH_MAX_AGE_SECONDS
        )
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
    # Tapping again renews the one pass rather than adding another.
    insert = insert_for(session, CatalogPass.__table__).values(
        user_id=caller.user_id, chat_id=chat_id, expires_at=expires_at, created_at=utc_now()
    )
    await session.execute(
        insert.on_conflict_do_update(
            index_elements=["user_id", "chat_id"], set_={"expires_at": insert.excluded.expires_at}
        )
    )
    await session.commit()
    logger.info("catalog_pass_noted", chat_id=chat_id, user_id=caller.user_id)
    return CatalogPassResult(status="noted")
