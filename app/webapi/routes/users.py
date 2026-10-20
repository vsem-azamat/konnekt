"""Users — global blacklist (block / unblock) endpoints.

Block/unblock are global ops that touch every managed chat — they reuse the
existing ``app.moderation.blacklist`` service unchanged. The webapi-owned
``publish_bot`` (Phase 4b) is the outgoing Telegram client.
"""

from __future__ import annotations

from typing import Annotated

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ModerationEventAction, ModerationEventSource
from app.core.exceptions import NotAPersonError, ProtectedUserError, UserNotFoundException
from app.db.models import User
from app.moderation import audit
from app.moderation.blacklist import add_to_blacklist, approved_chat_ids, remove_from_blacklist
from app.webapi.deps import get_publish_bot, get_session, require_super_admin
from app.webapi.schemas import BlockedUserRead, UserBlockRequest, UserBlockResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/blocked", response_model=list[BlockedUserRead])
async def list_blocked_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> list[BlockedUserRead]:
    """Everybody on the global blacklist, most recently changed first.

    Declared before `/{user_id}`: that route would take «blocked» for an id and
    refuse it as not a number.
    """
    rows = await session.scalars(select(User).where(User.blocked).order_by(User.modified_at.desc()))
    return [
        BlockedUserRead(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            changed_at=user.modified_at,
        )
        for user in rows
    ]


@router.post("/{user_id}/block", response_model=UserBlockResponse)
async def block_user(
    user_id: int,
    payload: UserBlockRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> UserBlockResponse:
    try:
        chats = len(await approved_chat_ids(session))
        failed = await add_to_blacklist(
            session, bot, user_id, revoke_messages=payload.revoke_messages or None, actor_id=admin_id
        )
    except ProtectedUserError as err:
        raise HTTPException(status_code=400, detail="A super admin cannot be banned") from err
    except NotAPersonError as err:
        raise HTTPException(
            status_code=400, detail="This id stands for channel or anonymous posts, not a person"
        ) from err
    await audit.record(
        session,
        action=ModerationEventAction.BLACKLIST,
        source=ModerationEventSource.CONSOLE,
        actor_id=admin_id,
        target_user_id=user_id,
    )
    return UserBlockResponse(
        user_id=user_id,
        blocked=True,
        message="User blocked across all managed chats." + (" Messages revoked." if payload.revoke_messages else ""),
        failed_chats=failed,
        banned_in=chats - len(failed),
    )


@router.delete("/{user_id}/block", response_model=UserBlockResponse)
async def unblock_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    bot: Annotated[Bot, Depends(get_publish_bot)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> UserBlockResponse:
    try:
        await remove_from_blacklist(session, bot, user_id)
    except UserNotFoundException as err:
        raise HTTPException(status_code=404, detail=f"User {user_id} not in DB") from err
    await audit.record(
        session,
        action=ModerationEventAction.UNBLACKLIST,
        source=ModerationEventSource.CONSOLE,
        actor_id=admin_id,
        target_user_id=user_id,
    )
    return UserBlockResponse(user_id=user_id, blocked=False, message="User unblocked.")
