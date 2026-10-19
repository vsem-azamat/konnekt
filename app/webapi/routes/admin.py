"""Admin / settings — read-only system status + active session management.

Mutations beyond ``revoke`` are intentionally out of scope: most settings
(feature flags, model choices, env-driven config) live in the deployment
config and would need schema work to become DB-backed. The /settings page
is a security + observability surface, not a config editor.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AdminSession
from app.webapi.auth import session_store
from app.webapi.deps import get_session, require_super_admin
from app.webapi.schemas import AdminSessionRead, FeatureFlagRead, SystemStatus

router = APIRouter(prefix="/admin", tags=["admin"])


async def _own_sessions(session: AsyncSession, admin_id: int) -> list[AdminSession]:
    query = select(AdminSession).where(AdminSession.user_id == admin_id).order_by(AdminSession.last_seen_at.desc())
    return list((await session.execute(query)).scalars().all())


@router.get("/sessions", response_model=list[AdminSessionRead])
async def list_sessions(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> list[AdminSessionRead]:
    """List the calling admin's active sessions, current one flagged."""
    current_token = request.cookies.get(settings.webapi.session_cookie_name)
    return [
        AdminSessionRead(
            id=session_store.public_id(r.session_id),
            user_id=r.user_id,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            expires_at=r.expires_at,
            user_agent=r.user_agent,
            ip=r.ip,
            is_current=current_token is not None and r.session_id == session_store.digest(current_token),
        )
        for r in await _own_sessions(session, admin_id)
    ]


@router.delete("/sessions/{public_id}", status_code=204)
async def revoke_session(
    public_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_id: Annotated[int, Depends(require_super_admin)],
) -> None:
    """Revoke one of the calling admin's sessions. Refuse to revoke the current one.

    Only the caller's own sessions are searched, so another admin's is simply
    not found.
    """
    row = next(
        (r for r in await _own_sessions(session, admin_id) if session_store.public_id(r.session_id) == public_id), None
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    current_token = request.cookies.get(settings.webapi.session_cookie_name)
    if current_token is not None and row.session_id == session_store.digest(current_token):
        raise HTTPException(status_code=400, detail="The current session cannot close itself")
    await session_store.revoke_session(session, row.session_id)


@router.get("/system", response_model=SystemStatus)
async def get_system_status(
    request: Request,
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> SystemStatus:

    publish_bot = getattr(request.app.state, "publish_bot", None)
    return SystemStatus(
        super_admin_ids=list(settings.admin.super_admins),
        publish_bot_ready=publish_bot is not None,
        allowed_origins=list(settings.webapi.allowed_origins),
        session_ttl_days=settings.webapi.session_ttl_days,
        feature_flags=[
            FeatureFlagRead(name="auth_telegram_webapp", enabled=True),
            FeatureFlagRead(name="ad_detector_enabled", enabled=settings.moderation.ad_detector_enabled),
        ],
    )
