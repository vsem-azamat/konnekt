"""The Mini App telling us it was opened, for the audience.

The one public endpoint that writes (see docs/invariants.md). Its credential
is Telegram's signature over ``initData``, as at the join check: nobody can
claim to be somebody else without the bot token. It is idempotent: the visit
is dated by the payload's ``auth_date``, which names one launch, so a payload
sent again counts once. A person is written at most once per
`MIN_INTERVAL`; past that the request is answered and nothing is written.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audience import record
from app.audience.record import SOURCE, Person
from app.core.config import settings
from app.core.enums import Touchpoint
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data
from app.webapi.deps import get_session

router = APIRouter(prefix="/public", tags=["public"])

MIN_INTERVAL = 30.0
# Per process, as the throttles in the bot are; a forgotten entry only lets one more write through.
_last_written: dict[int, float] = {}
_REMEMBERED = 10_000


class SeenRequest(BaseModel):
    init_data: str = Field(description="Raw Telegram.WebApp.initData string", max_length=4096)


def forget() -> None:
    """For tests: start with nobody written recently."""
    _last_written.clear()


@router.post("/seen", status_code=status.HTTP_204_NO_CONTENT)
async def mini_app_opened(payload: SeenRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> Response:
    """Record that the caller opened the Mini App."""
    try:
        caller = verify_init_data(payload.init_data, bot_token=settings.telegram.token)
    except InitDataError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="check_failed") from None

    now = time.monotonic()
    if now - _last_written.get(caller.user_id, -MIN_INTERVAL) < MIN_INTERVAL:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Telegram asks the person on launch whether the bot may write to them.
    started = Touchpoint.MAIN_BOT if caller.raw_user.get("allows_write_to_pm") else None
    await record.seen(
        session,
        Person.from_web_app(caller.raw_user),
        Touchpoint.MINI_APP,
        at=caller.auth_date,
        source=caller.start_param if caller.start_param and SOURCE.fullmatch(caller.start_param) else None,
        started=started,
    )
    await session.commit()
    # Only once it is written: a failed write must not hold the next launch back.
    if len(_last_written) >= _REMEMBERED:
        _last_written.clear()
    _last_written[caller.user_id] = now
    return Response(status_code=status.HTTP_204_NO_CONTENT)
