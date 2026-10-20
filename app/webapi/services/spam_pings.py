"""What the ad detector caught, as the console reads it and answers it."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, false, func, or_, select

from app.core.enums import SpamVerdict
from app.core.time import utc_now
from app.db.models import Chat, SpamPing, User
from app.webapi.schemas import SpamPingRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PingStatus = Literal["all", "unreviewed", "not_ad"]

# A hit waits in the queue until a moderator answers it or bans its author:
# a ban is the verdict on every hit of theirs, so none is written per hit.
_UNREVIEWED = and_(SpamPing.verdict.is_(None), func.coalesce(User.blocked, false()).is_(false()))


async def read_pings(
    session: AsyncSession,
    *,
    chat_id: int | None,
    limit: int,
    status: PingStatus = "all",
    days: int | None = None,
    before_id: int | None = None,
) -> list[SpamPingRead]:
    """Ad-detector hits, newest first, with the chat's title and the author.

    ``before_id`` continues a list after the hit of that id, so a page ends
    where the last one stopped even when two hits share a second. Chats and
    users the bot never stored come back without a title or a name; an author
    with no row cannot be on the blacklist either.
    """
    stmt = (
        select(SpamPing, Chat.title, User)
        .join(Chat, Chat.id == SpamPing.chat_id, isouter=True)
        .join(User, User.id == SpamPing.user_id, isouter=True)
        .order_by(SpamPing.detected_at.desc(), SpamPing.id.desc())
        .limit(limit)
    )
    if chat_id is not None:
        stmt = stmt.where(SpamPing.chat_id == chat_id)
    if status == "unreviewed":
        stmt = stmt.where(_UNREVIEWED)
    elif status == "not_ad":
        stmt = stmt.where(SpamPing.verdict == SpamVerdict.NOT_AD)
    if days is not None:
        stmt = stmt.where(SpamPing.detected_at >= utc_now() - datetime.timedelta(days=days))
    if before_id is not None:
        after = await session.get(SpamPing, before_id)
        if after is None:
            return []
        stmt = stmt.where(
            or_(
                SpamPing.detected_at < after.detected_at,
                and_(SpamPing.detected_at == after.detected_at, SpamPing.id < after.id),
            )
        )

    rows = (await session.execute(stmt)).all()
    return [_read(ping, title, user) for ping, title, user in rows]


async def count_unreviewed(session: AsyncSession) -> int:
    """How many hits wait in the queue, of any age."""
    stmt = (
        select(func.count(SpamPing.id))
        .select_from(SpamPing)
        .join(User, User.id == SpamPing.user_id, isouter=True)
        .where(_UNREVIEWED)
    )
    return int((await session.execute(stmt)).scalar_one())


async def review_ping(
    session: AsyncSession, ping_id: int, verdict: SpamVerdict, *, admin_id: int
) -> SpamPingRead | None:
    """Records a moderator's answer to a hit; none for a hit that is gone."""
    ping = await session.get(SpamPing, ping_id)
    if ping is None:
        return None
    ping.verdict = verdict
    ping.reviewed_at = utc_now()
    ping.reviewed_by = admin_id
    await session.commit()
    title = await session.scalar(select(Chat.title).where(Chat.id == ping.chat_id))
    user = await session.get(User, ping.user_id)
    return _read(ping, title, user)


def _read(ping: SpamPing, title: str | None, user: User | None) -> SpamPingRead:
    return SpamPingRead(
        id=ping.id,
        chat_id=ping.chat_id,
        chat_title=title,
        user_id=ping.user_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        blocked=bool(user and user.blocked),
        message_id=ping.message_id,
        kind=ping.kind,
        matches=ping.matches,
        snippet=ping.snippet,
        detected_at=ping.detected_at,
        verdict=ping.verdict,
    )
