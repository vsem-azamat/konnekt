"""Home dashboard aggregator."""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.db.models import Chat, ChatMemberSnapshot, Message, SpamPing
from app.webapi.deps import get_session, require_super_admin
from app.webapi.schemas import (
    ChatHeatmapSummary,
    HomeStats,
    MembersDeltaEntry,
    SpamPingRead,
    SpamPingsSummary,
)
from app.webapi.services.spam_pings import count_unreviewed

router = APIRouter(prefix="/stats", tags=["stats"])

_DELTA_LOOKBACK_DAYS = 30
_CHAT_HEATMAP_TOP_N = 8
_CHAT_HEATMAP_LOOKBACK_DAYS = 7
_SPAM_RECENT_LIMIT = 5


async def _compute_members_delta(session: AsyncSession, now: datetime.datetime) -> list[MembersDeltaEntry]:
    """For every chat with ≥1 snapshot: current count + Δ over 24h / 7d.

    Baseline = oldest snapshot whose captured_at <= (now - window). If none,
    delta is None (e.g. a chat whose newest snapshot is older than 24h will
    have delta_24h=None but still appears with its stale current count).

    We cap the lookback at _DELTA_LOOKBACK_DAYS so old history doesn't
    accumulate unbounded in the result set. Chats with only stale snapshots
    (all older than _DELTA_LOOKBACK_DAYS) will not appear; that's an
    acceptable edge-case for very inactive chats.
    """
    lookback = now - datetime.timedelta(days=_DELTA_LOOKBACK_DAYS)
    rows = (
        await session.execute(
            select(ChatMemberSnapshot, Chat.title)
            .join(Chat, Chat.id == ChatMemberSnapshot.chat_id, isouter=True)
            .where(ChatMemberSnapshot.captured_at >= lookback)
            .order_by(ChatMemberSnapshot.captured_at.asc())
        )
    ).all()
    by_chat: dict[int, list[tuple[datetime.datetime, int, str | None]]] = {}
    for snap, title in rows:
        by_chat.setdefault(snap.chat_id, []).append((snap.captured_at, snap.member_count, title))

    out: list[MembersDeltaEntry] = []
    for chat_id, points in by_chat.items():
        if not points:
            continue
        title = points[-1][2]
        current = points[-1][1]
        # Search baselines only in snapshots that precede the current one so
        # a single-snapshot chat doesn't produce a spurious 0-delta.
        earlier = points[:-1]
        baseline_24h = next(
            (c for ts, c, _ in earlier if ts <= now - datetime.timedelta(hours=24)),
            None,
        )
        baseline_7d = next(
            (c for ts, c, _ in earlier if ts <= now - datetime.timedelta(days=7)),
            None,
        )
        out.append(
            MembersDeltaEntry(
                chat_id=chat_id,
                title=title,
                current=current,
                delta_24h=(current - baseline_24h) if baseline_24h is not None else None,
                delta_7d=(current - baseline_7d) if baseline_7d is not None else None,
            )
        )
    return out


@router.get("/home", response_model=HomeStats)
async def home_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> HomeStats:
    now = utc_now()

    # --- Chat heatmap summary (top N chats by total messages, last 7d) ---
    heatmap_since = now - datetime.timedelta(days=_CHAT_HEATMAP_LOOKBACK_DAYS)
    total_msgs = func.count(Message.id).label("total_msgs")
    heatmap_rows = (
        await session.execute(
            select(Message.chat_id, Chat.title, total_msgs)
            .join(Chat, Chat.id == Message.chat_id, isouter=True)
            .where(Message.timestamp >= heatmap_since)
            .group_by(Message.chat_id, Chat.title)
            .order_by(total_msgs.desc())
            .limit(_CHAT_HEATMAP_TOP_N)
        )
    ).all()
    chat_heatmap = [
        ChatHeatmapSummary(chat_id=row.chat_id, title=row.title, total_messages=int(row.total_msgs))
        for row in heatmap_rows
    ]

    # --- Members delta ---
    members_delta = await _compute_members_delta(session, now)

    # --- Spam pings: 24h / 7d counts + N most recent samples ---
    since_24h = now - datetime.timedelta(hours=24)
    since_7d = now - datetime.timedelta(days=7)
    count_24h = int(
        (await session.execute(select(func.count(SpamPing.id)).where(SpamPing.detected_at >= since_24h))).scalar_one()
    )
    count_7d = int(
        (await session.execute(select(func.count(SpamPing.id)).where(SpamPing.detected_at >= since_7d))).scalar_one()
    )
    recent_rows = (
        await session.execute(
            select(SpamPing, Chat.title)
            .join(Chat, Chat.id == SpamPing.chat_id, isouter=True)
            .order_by(SpamPing.detected_at.desc())
            .limit(_SPAM_RECENT_LIMIT)
        )
    ).all()
    recent = [
        SpamPingRead(
            id=p.id,
            chat_id=p.chat_id,
            chat_title=title,
            user_id=p.user_id,
            message_id=p.message_id,
            kind=p.kind,
            matches=p.matches,
            snippet=p.snippet,
            detected_at=p.detected_at,
        )
        for p, title in recent_rows
    ]

    return HomeStats(
        chat_heatmap=chat_heatmap,
        members_delta=members_delta,
        spam_pings=SpamPingsSummary(
            count_24h=count_24h, count_7d=count_7d, unreviewed=await count_unreviewed(session), recent=recent
        ),
    )
