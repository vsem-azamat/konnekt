"""Home dashboard aggregator."""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, nulls_last, select
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
# The bot counts members hourly; a newest count older than this is not today's.
_FRESH = datetime.timedelta(hours=2)
_CHAT_HEATMAP_TOP_N = 8
_SPAM_RECENT_LIMIT = 5


async def _compute_members_delta(session: AsyncSession, now: datetime.datetime) -> list[MembersDeltaEntry]:
    """For every chat we run with a count: its newest count and how far it
    moved over 24h and over 7 days.

    Each window compares with the newest count taken at or before its start;
    none taken that early leaves that window unknown. A chat whose newest
    count is older than _FRESH stopped being counted, so neither window says
    it moved. Counts older than _DELTA_LOOKBACK_DAYS are not read.
    """
    lookback = now - datetime.timedelta(days=_DELTA_LOOKBACK_DAYS)
    rows = (
        await session.execute(
            select(ChatMemberSnapshot, Chat.title)
            .join(Chat, Chat.id == ChatMemberSnapshot.chat_id)
            .where(ChatMemberSnapshot.captured_at >= lookback, Chat.resource_status == Chat.STATUS_APPROVED)
            .order_by(ChatMemberSnapshot.captured_at.asc())
        )
    ).all()
    by_chat: dict[int, list[tuple[datetime.datetime, int, str | None]]] = {}
    for snap, title in rows:
        by_chat.setdefault(snap.chat_id, []).append((snap.captured_at, snap.member_count, title))

    def moved(points: list[tuple[datetime.datetime, int, str | None]], window: datetime.timedelta) -> int | None:
        newest_at, current, _ = points[-1]
        if newest_at < now - _FRESH:
            return None
        start = now - window
        # Newest first: the first count at or before the window's start.
        baseline = next((count for at, count, _ in reversed(points[:-1]) if at <= start), None)
        return None if baseline is None else current - baseline

    return [
        MembersDeltaEntry(
            chat_id=chat_id,
            title=points[-1][2],
            current=points[-1][1],
            delta_24h=moved(points, datetime.timedelta(hours=24)),
            delta_7d=moved(points, datetime.timedelta(days=7)),
        )
        for chat_id, points in by_chat.items()
    ]


async def _busiest_chats(session: AsyncSession, now: datetime.datetime) -> list[ChatHeatmapSummary]:
    """The chats that wrote most in the last 24 hours, each by UTC hour of day.

    The hours are counted from the timestamps of those few chats only, in
    Python as /chats/:id does, so no dialect's date functions are involved.
    """
    since = now - datetime.timedelta(hours=24)
    total = func.count(Message.id).label("total")
    top = (
        await session.execute(
            select(Message.chat_id, Chat.title, total)
            .join(Chat, Chat.id == Message.chat_id, isouter=True)
            .where(Message.timestamp >= since)
            .group_by(Message.chat_id, Chat.title)
            .order_by(total.desc(), nulls_last(Chat.title.asc()), Message.chat_id)
            .limit(_CHAT_HEATMAP_TOP_N)
        )
    ).all()
    hours: dict[int, list[int]] = {row.chat_id: [0] * 24 for row in top}
    stamps = await session.execute(
        select(Message.chat_id, Message.timestamp).where(Message.chat_id.in_(hours), Message.timestamp >= since)
    )
    for chat_id, at in stamps:
        hours[chat_id][at.hour] += 1
    return [
        ChatHeatmapSummary(
            # The hours' sum, not the first query's count: a message stamped
            # between the two queries is in both counts or in neither.
            chat_id=row.chat_id,
            title=row.title,
            total_messages=sum(hours[row.chat_id]),
            hours=hours[row.chat_id],
        )
        for row in top
    ]


@router.get("/home", response_model=HomeStats)
async def home_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin_id: Annotated[int, Depends(require_super_admin)],
) -> HomeStats:
    now = utc_now()

    # --- The busiest chats of the last day, by hour ---
    chat_heatmap = await _busiest_chats(session, now)

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
