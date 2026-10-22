"""What waits for an admin's decision, for the console's bell and its menu.

The waves and the proposals are the ones the bot asks about in the report
chat; the console shows the same ones, so a decision taken there shows here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from aiogram import Bot
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.captcha import waves
from app.core.exceptions import ChatNotManagedError, ProtectedUserError
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, JoinWave, PendingAction, User
from app.db.session import get_session_maker
from app.moderation import pending_actions
from app.webapi.deps import get_publish_bot, get_session, require_super_admin
from app.webapi.schemas import PendingActionSignal, SignalQueues, Signals, WaveSignal
from app.webapi.services.member_counts import latest_for
from app.webapi.services.spam_pings import count_unreviewed

logger = get_logger("webapi.signals")

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
                quiet_until=waves.quiet_until(wave),
            )
            for wave, held in held_waves
        ],
        wave_per_minute=waves.PER_MINUTE,
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
    if await waves.record(session, wave_id=wave_id, action=payload.action, admin_id=admin_id, now=utc_now()) is None:
        raise HTTPException(status_code=409, detail="decided otherwise")
    background.add_task(_decide_wave, bot, wave_id, payload.action, admin_id, await _admin_name(session, admin_id))
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


class ProposalDecisionRequest(BaseModel):
    confirm: bool


# The bot's own words for the same outcomes, so its message and the console agree.
_DONE = "Подтверждено в консоли и выполнено."
_DROPPED = "Отклонено в консоли. Ничего не выполнено."
_PROTECTED = "Не выполнено: главного администратора забанить нельзя."
_UNMANAGED = "Не выполнено: бот больше не модерирует этот чат. Запрос закрыт."
_FAILED = "Не выполнено: Telegram отказал. Запрос закрыт, ничего не изменилось."


@router.post("/actions/{pending_id}")
async def decide_proposal(
    pending_id: int,
    payload: ProposalDecisionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> dict[str, str]:
    """Confirm or reject a proposal from MCP, as its buttons in the bot's message would."""
    service = pending_actions.PendingActionService(bot, session)
    try:
        resolved = (
            await service.confirm(pending_id, admin_id=admin_id)
            if payload.confirm
            else await service.reject(pending_id, admin_id=admin_id)
        )
    except ProtectedUserError as err:
        await _close(service, session, pending_id, _PROTECTED)
        raise HTTPException(status_code=409, detail="protected") from err
    except ChatNotManagedError as err:
        await _close(service, session, pending_id, _UNMANAGED)
        raise HTTPException(status_code=409, detail="unmanaged") from err
    except Exception as err:
        # Recorded as failed by the service.
        logger.warning("console_proposal_failed", pending_id=pending_id, exc_info=True)
        await _close(service, session, pending_id, _FAILED)
        raise HTTPException(status_code=502, detail="failed") from err
    if resolved is None:
        # Already pressed, already gone, or its deadline passed; whoever closed it said so.
        raise HTTPException(status_code=409, detail="gone")
    await service.close_message(resolved, _DONE if payload.confirm else _DROPPED)
    return {"outcome": "confirmed" if payload.confirm else "rejected"}


async def _close(
    service: pending_actions.PendingActionService, session: AsyncSession, pending_id: int, note: str
) -> None:
    pending = await session.get(PendingAction, pending_id, populate_existing=True)
    if pending is not None:
        await service.close_message(pending, note)
