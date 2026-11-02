"""What waits for an admin's decision, for the console's bell and its menu.

The waves are the ones the bot asks about in the report chat; the console
shows the same ones, so a decision taken there shows here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from aiogram import Bot
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import waves
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinWave, User
from app.db.session import get_session_maker
from app.webapi.deps import get_publish_bot, get_session, require_super_admin
from app.webapi.schemas import SignalQueues, Signals, WaveSignal
from app.webapi.services.member_counts import latest_for
from app.webapi.services.spam_pings import count_unreviewed, unreviewed_since

logger = get_logger("webapi.signals")

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=Signals)
async def read_signals(session: Annotated[AsyncSession, Depends(get_session)]) -> Signals:
    now = utc_now()
    held_waves = await waves.undecided(session, now)

    chat_ids = {wave.chat_id for wave, _ in held_waves}
    titles = dict((await session.execute(select(Chat.id, Chat.title).where(Chat.id.in_(chat_ids)))).tuples().all())
    members = await latest_for(session, [wave.chat_id for wave, _ in held_waves])

    # Found when the bot first met the chat, so it waits from then.
    in_review, review_since = (
        await session.execute(
            select(func.count(Chat.id), func.min(Chat.created_at)).where(Chat.resource_status == Chat.STATUS_DISCOVERED)
        )
    ).one()
    return Signals(
        waves=[
            WaveSignal(
                id=wave.id,
                chat_id=wave.chat_id,
                chat_title=titles.get(wave.chat_id),
                member_count=members.get(wave.chat_id),
                started_at=wave.started_at,
                last_surge_at=wave.last_surge_at,
                held=held,
                paused=waves.paused_at(wave, now),
                quiet_until=waves.quiet_until(wave),
            )
            for wave, held in held_waves
        ],
        wave_per_minute=waves.PER_MINUTE,
        queues=SignalQueues(
            ads_unreviewed=await count_unreviewed(session),
            ads_waiting_since=await unreviewed_since(session),
            chats_in_review=in_review,
            chats_waiting_since=review_since,
        ),
    )


class WaveDecisionRequest(BaseModel):
    """The report chat's three buttons, by the names `waves` gives them."""

    action: Literal["decline", "resume", "leave"]


@router.post("/waves/{wave_id}/decision", status_code=202)
async def decide_wave(
    wave_id: int,
    payload: WaveDecisionRequest,
    background: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> dict[str, str]:
    """Settle a wave as its button in the report chat would.

    Answered before the work, as the button is: declining a wave of hundreds
    takes minutes of Telegram calls. The alert in the report chat says the
    outcome once it is done, and the wave leaves the signals at once.
    """
    if await session.get(JoinWave, wave_id) is None:
        raise HTTPException(status_code=404, detail="no such wave")
    # Written down before the answer, so the next reading of the signals no
    # longer lists it; the work then finds the same decision and carries on.
    wave = await waves.record(session, wave_id=wave_id, action=payload.action, admin_id=admin_id, now=utc_now())
    if wave is None:
        raise HTTPException(status_code=409, detail="decided otherwise")
    admin_name = await _admin_name(session, admin_id)
    if payload.action == waves.DECLINE:
        # Declining takes minutes; the alert says it began, so a restart
        # halfway leaves it half-done rather than looking undecided.
        await waves.announce_declining(bot, session, wave, admin_name)
    background.add_task(_decide_wave, bot, wave_id, payload.action, admin_id, admin_name)
    return {"accepted": payload.action}


async def _decide_wave(bot: Bot, wave_id: int, action: str, admin_id: int, admin_name: str) -> None:
    async with get_session_maker()() as session:
        try:
            await waves.decide(bot, session, wave_id=wave_id, action=action, admin_id=admin_id, admin_name=admin_name)
        except Exception:
            # Nobody is waiting on the answer any more; the log is where this goes.
            logger.exception("console_wave_decision_failed", wave_id=wave_id, action=action)


async def _admin_name(session: AsyncSession, admin_id: int) -> str:
    """How the report chat names the admin, with where they pressed."""
    user = await session.get(User, admin_id)
    name = " ".join(filter(None, (user.first_name, user.last_name))) if user else ""
    return f"{name or admin_id} (консоль)"
