"""The Mini App endpoint that lets an applicant through the door.

Unauthenticated in the session sense — its credential is Telegram's signature
over ``initData``, which the applicant's own client produces and nobody else
can forge without the bot token.

Every refusal is the same 403 with no detail. Which check failed is useful only
to somebody probing the endpoint: a legitimate caller's payload is assembled by
Telegram, so it either verifies or the client is not Telegram.
"""

from __future__ import annotations

from typing import Annotated

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import JoinCheck
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_publish_bot, get_session

logger = get_logger("webapi.join_check")

router = APIRouter(prefix="/public", tags=["public"])

_REFUSED = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="check_failed")


class JoinCheckRequest(BaseModel):
    init_data: str = Field(description="Raw Telegram.WebApp.initData string")
    query_id: str = Field(description="Join request query id, carried in the Mini App URL")


class JoinCheckResult(BaseModel):
    status: str


@router.post("/join-check", response_model=JoinCheckResult)
async def pass_join_check(
    payload: JoinCheckRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
) -> JoinCheckResult:
    """Approve the caller's own pending join request."""
    try:
        caller = verify_init_data(payload.init_data, bot_token=settings.telegram.token)
    except InitDataError:
        logger.info("join_check_signature_refused")
        raise _REFUSED from None

    check = await session.scalar(select(JoinCheck).where(JoinCheck.query_id == payload.query_id))
    if check is None or check.passed_at is not None or check.expires_at <= utc_now():
        logger.info("join_check_unavailable", user_id=caller.user_id)
        raise _REFUSED

    if check.user_id != caller.user_id:
        # The reason this table exists: holding a query id is not the same as
        # being the person it was issued to.
        logger.warning("join_check_wrong_applicant", user_id=caller.user_id, expected=check.user_id)
        raise _REFUSED

    # Claimed before the call, in one statement, so a double tap cannot
    # answer the same query twice.
    claimed = await session.execute(
        update(JoinCheck)
        .where(JoinCheck.query_id == payload.query_id, JoinCheck.passed_at.is_(None))
        .values(passed_at=utc_now())
    )
    await session.commit()
    if claimed.rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise _REFUSED

    try:
        await bot.answer_chat_join_request_query(chat_join_request_query_id=payload.query_id, result="approve")
    except TelegramBadRequest:
        # Answered already, or gone: asking again cannot help, so it stays spent.
        logger.warning("join_check_answer_refused", chat_id=check.chat_id, user_id=caller.user_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="query_closed") from None
    except Exception:
        # Telegram never heard: release the claim so the applicant can try again
        # rather than wait on a moderator for a check they passed.
        await session.execute(update(JoinCheck).where(JoinCheck.query_id == payload.query_id).values(passed_at=None))
        await session.commit()
        logger.warning("join_check_answer_failed", chat_id=check.chat_id, user_id=caller.user_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="try_again") from None
    logger.info("join_check_passed", chat_id=check.chat_id, user_id=caller.user_id)
    return JoinCheckResult(status="approved")
