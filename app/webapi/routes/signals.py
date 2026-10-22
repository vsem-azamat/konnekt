"""What waits for an admin's decision, for the console's bell and its menu.

The waves and the proposals are the ones the bot asks about in the report
chat; the console shows the same ones, so a decision taken there shows here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import waves
from app.core.time import utc_now
from app.db.models import Chat, PendingAction, User
from app.moderation import pending_actions
from app.webapi.deps import get_session
from app.webapi.schemas import PendingActionSignal, SignalQueues, Signals, WaveSignal
from app.webapi.services.member_counts import latest_for
from app.webapi.services.spam_pings import count_unreviewed

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=Signals)
async def read_signals(session: Annotated[AsyncSession, Depends(get_session)]) -> Signals:
    now = utc_now()
    held_waves = await waves.undecided(session, now)
    proposals = await pending_actions.awaiting(session)

    chat_ids = {wave.chat_id for wave, _ in held_waves} | {p.chat_id for p in proposals if p.chat_id is not None}
    titles = dict((await session.execute(select(Chat.id, Chat.title).where(Chat.id.in_(chat_ids)))).tuples().all())
    members = await latest_for(session, [wave.chat_id for wave, _ in held_waves])
    targets = {
        user.id: user
        for user in await session.scalars(select(User).where(User.id.in_({p.target_user_id for p in proposals})))
    }

    in_review = await session.scalar(select(func.count(Chat.id)).where(Chat.resource_status == Chat.STATUS_DISCOVERED))
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
            )
            for wave, held in held_waves
        ],
        pending_actions=[_proposal(p, titles, targets.get(p.target_user_id)) for p in proposals],
        queues=SignalQueues(ads_unreviewed=await count_unreviewed(session), chats_in_review=in_review or 0),
    )


def _proposal(p: PendingAction, titles: dict[int, str | None], target: User | None) -> PendingActionSignal:
    name = " ".join(filter(None, (target.first_name, target.last_name))) if target else ""
    return PendingActionSignal(
        id=p.id,
        action=p.action,  # ty: ignore[invalid-argument-type]
        chat_id=p.chat_id,
        chat_title=titles.get(p.chat_id) if p.chat_id is not None else None,
        target_user_id=p.target_user_id,
        target_username=target.username if target else None,
        target_name=name or None,
        reason=p.reason,
        created_at=p.created_at,
        expires_at=p.expires_at,
    )
