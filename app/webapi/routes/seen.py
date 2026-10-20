"""The Mini App telling us it was opened, for the audience.

Its credential is Telegram's signature over ``initData``, as at the join
check: nobody can claim to be somebody else without the bot token. A refusal
is a bare 403. The Mini App calls this once at launch and does not wait on
the answer, so nothing here can hold up the app.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audience import record
from app.audience.record import Person
from app.core.config import settings
from app.core.enums import Touchpoint
from app.core.logging import get_logger
from app.core.time import utc_now
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session

logger = get_logger("webapi.seen")

router = APIRouter(prefix="/public", tags=["public"])


class SeenRequest(BaseModel):
    init_data: str = Field(description="Raw Telegram.WebApp.initData string")


@router.post("/seen", status_code=status.HTTP_204_NO_CONTENT)
async def mini_app_opened(payload: SeenRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> Response:
    """Record that the caller opened the Mini App."""
    try:
        caller = verify_init_data(payload.init_data, bot_token=settings.telegram.token)
    except InitDataError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="check_failed") from None

    # Telegram asks the person on launch whether the bot may write to them.
    started = Touchpoint.MAIN_BOT if caller.raw_user.get("allows_write_to_pm") else None
    source = caller.start_param[:64] if caller.start_param else None
    await record.seen(
        session, Person.from_web_app(caller.raw_user), Touchpoint.MINI_APP, at=utc_now(), source=source, started=started
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
