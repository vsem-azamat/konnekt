"""What the ad detector caught, as the console reads it and answers it."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, literal, select, tuple_, update

from app.core.enums import SpamVerdict
from app.core.time import utc_now
from app.db.models import Chat, SpamPing, User
from app.webapi.schemas import SpamPingRead

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncSession

PingStatus = Literal["all", "unreviewed", "not_ad"]

# A hit waits in the queue until it has a verdict: a moderator's in the
# console, or «ad» from a ban of its author (moderation/blacklist.py).
_UNREVIEWED = SpamPing.verdict.is_(None)


async def read_pings(
    session: AsyncSession,
    *,
    chat_id: int | None,
    limit: int,
    status: PingStatus = "all",
    days: int | None = None,
    before: tuple[datetime.datetime, int] | None = None,
) -> list[SpamPingRead]:
    """Ad-detector hits, newest first, with the chat's title and the author.

    ``before`` is the last hit of the previous page, as its time and id: a page
    goes on from there even when two hits share a second, or when that hit is
    gone since. Chats and users the bot never stored come back without a title
    or a name; an author with no row cannot be on the blacklist either.
    """
    stmt = (
        select(SpamPing, Chat.title, User)
        .join(Chat, Chat.id == SpamPing.chat_id, isouter=True)
        .join(User, User.id == SpamPing.user_id, isouter=True)
        .where(*_filters(chat_id=chat_id, status=status, days=days))
        .order_by(SpamPing.detected_at.desc(), SpamPing.id.desc())
        .limit(limit)
    )
    if before is not None:
        at, ping_id = before
        stmt = stmt.where(tuple_(SpamPing.detected_at, SpamPing.id) < tuple_(literal(at), literal(ping_id)))

    rows = (await session.execute(stmt)).all()
    return [_read(ping, title, user) for ping, title, user in rows]


async def count_unreviewed(session: AsyncSession, *, chat_id: int | None = None, days: int | None = None) -> int:
    """How many hits wait in the queue, under the same filters as the list."""
    stmt = select(func.count(SpamPing.id)).where(*_filters(chat_id=chat_id, status="unreviewed", days=days))
    return int((await session.execute(stmt)).scalar_one())


def _filters(*, chat_id: int | None, status: PingStatus, days: int | None) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = []
    if chat_id is not None:
        where.append(SpamPing.chat_id == chat_id)
    if status == "unreviewed":
        where.append(_UNREVIEWED)
    elif status == "not_ad":
        where.append(SpamPing.verdict == SpamVerdict.NOT_AD)
    if days is not None:
        where.append(SpamPing.detected_at >= utc_now() - datetime.timedelta(days=days))
    return where


class AlreadyAnsweredError(Exception):
    """Somebody answered the hit first; carries it as it now is."""

    def __init__(self, ping: SpamPingRead) -> None:
        super().__init__(f"spam ping {ping.id} already answered")
        self.ping = ping


async def review_ping(
    session: AsyncSession, ping_id: int, verdict: SpamVerdict, *, admin_id: int
) -> SpamPingRead | None:
    """Records a moderator's answer to a hit still waiting; none for a hit
    that is gone, AlreadyAnsweredError for one answered meanwhile.

    One conditional UPDATE, so of two moderators on one hit the first answer
    stands and the second hears so, whatever the timing.
    """
    answered = await session.scalar(
        update(SpamPing)
        .where(SpamPing.id == ping_id, _UNREVIEWED)
        .values(verdict=verdict, reviewed_at=utc_now(), reviewed_by=admin_id)
        .returning(SpamPing.id)
    )
    await session.commit()
    ping = await _one(session, ping_id)
    if answered is None and ping is not None:
        raise AlreadyAnsweredError(ping)
    return ping


async def _one(session: AsyncSession, ping_id: int) -> SpamPingRead | None:
    row = (
        await session.execute(
            select(SpamPing, Chat.title, User)
            .join(Chat, Chat.id == SpamPing.chat_id, isouter=True)
            .join(User, User.id == SpamPing.user_id, isouter=True)
            .where(SpamPing.id == ping_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    return _read(*row) if row else None


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
