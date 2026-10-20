"""Reading the audience for the console: the summary, a filtered page, one person.

A person's status is about the main bot, the one any announcement would come
from, and the four statuses do not overlap: opting out outranks a block,
which outranks having started the bot.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import and_, case, func, or_, select

from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

Status = Literal["reachable", "never_started", "blocked", "opted_out"]
STATUSES: tuple[Status, ...] = ("reachable", "never_started", "blocked", "opted_out")
WEEKS = 8

_main = (
    select(AudienceReach.user_id, AudienceReach.started_at, AudienceReach.blocked_at)
    .where(AudienceReach.bot == Touchpoint.MAIN_BOT)
    .subquery()
)
_status = case(
    (AudienceMember.opted_out_at.is_not(None), "opted_out"),
    (_main.c.blocked_at.is_not(None), "blocked"),
    (_main.c.started_at.is_not(None), "reachable"),
    else_="never_started",
)


def _members() -> Any:
    """Every member with their status, ready for more conditions."""
    return select(AudienceMember, _status.label("status")).outerjoin(_main, _main.c.user_id == AudienceMember.user_id)


def new_since(now: datetime.datetime, days: int) -> datetime.datetime:
    """Where "new in the last `days`" starts: one window for the summary and the list alike."""
    return now - datetime.timedelta(days=days)


async def summary(db: AsyncSession, *, now: datetime.datetime) -> dict[str, Any]:
    members = _members().subquery()
    reach = dict.fromkeys(STATUSES, 0)
    for status, count in await db.execute(select(members.c.status, func.count()).group_by(members.c.status)):
        reach[status] = count

    # Weeks counted back from now, not calendar weeks: the last bar is always the latest seven days.
    bounds = [new_since(now, 7 * weeks) for weeks in range(WEEKS + 1)]
    weekly = await db.execute(
        select(
            *(
                func.count().filter(
                    AudienceMember.first_seen_at > bounds[age + 1], AudienceMember.first_seen_at <= bounds[age]
                )
                for age in reversed(range(WEEKS))
            )
        )
    )
    new_by_week = [count or 0 for count in weekly.one()]

    # The touchpoint each person used first; a tie, as the backfill can leave, is broken by name.
    first = (
        select(
            AudienceTouch.touchpoint,
            func.row_number()
            .over(partition_by=AudienceTouch.user_id, order_by=(AudienceTouch.first_at, AudienceTouch.touchpoint))
            .label("rank"),
        )
    ).subquery()
    first_touch = {touchpoint.value: 0 for touchpoint in Touchpoint}
    for touchpoint, count in await db.execute(
        select(first.c.touchpoint, func.count()).where(first.c.rank == 1).group_by(first.c.touchpoint)
    ):
        first_touch[touchpoint] = count

    languages = await db.execute(
        select(AudienceMember.language_code, func.count().label("n"))
        .where(AudienceMember.language_code.is_not(None))
        .group_by(AudienceMember.language_code)
        .order_by(func.count().desc(), AudienceMember.language_code)
    )
    return {
        "total": sum(reach.values()),
        "reach": reach,
        "first_touch": first_touch,
        "new_by_week": new_by_week,
        "new_this_week": new_by_week[-1],
        "languages": [{"code": code, "count": count} for code, count in languages],
    }


# A Telegram id fits a signed bigint; a longer run of digits is a name, not an id.
_MAX_ID = 2**63 - 1


async def page(
    db: AsyncSession,
    *,
    now: datetime.datetime,
    touchpoint: Touchpoint | None = None,
    status: Status | None = None,
    language: str | None = None,
    query: str | None = None,
    new_days: int | None = None,
    limit: int = 50,
    after: tuple[datetime.datetime, int] | None = None,
) -> dict[str, Any]:
    """Members newest activity first, with the touchpoints each has used.

    Paged by keyset: `after` is the (last_seen_at, user_id) of the last row
    shown, and the answer's `next` is the one to ask with next. An offset
    would skip or repeat people as their activity moves them up the list.
    """
    statement = _members()
    if touchpoint is not None:
        used = select(AudienceTouch.user_id).where(AudienceTouch.touchpoint == touchpoint)
        statement = statement.where(AudienceMember.user_id.in_(used))
    if status is not None:
        statement = statement.where(_status == status)
    if language is not None:
        statement = statement.where(AudienceMember.language_code == language)
    if new_days is not None:
        statement = statement.where(AudienceMember.first_seen_at > new_since(now, new_days))
    if query := (query or "").strip().removeprefix("@"):
        # Searched for as typed: % and _ are letters here, not patterns.
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        matches = [
            AudienceMember.username.ilike(like, escape="\\"),
            AudienceMember.first_name.ilike(like, escape="\\"),
            AudienceMember.last_name.ilike(like, escape="\\"),
        ]
        if query.isdecimal() and int(query) <= _MAX_ID:
            matches.append(AudienceMember.user_id == int(query))
        statement = statement.where(or_(*matches))

    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    if after is not None:
        seen_at, user_id = after
        statement = statement.where(
            or_(
                AudienceMember.last_seen_at < seen_at,
                and_(AudienceMember.last_seen_at == seen_at, AudienceMember.user_id > user_id),
            )
        )
    rows = (
        await db.execute(statement.order_by(AudienceMember.last_seen_at.desc(), AudienceMember.user_id).limit(limit))
    ).all()
    touchpoints = await _touchpoints(db, [member.user_id for member, _ in rows])
    last = rows[-1][0] if len(rows) == limit else None
    return {
        "total": total or 0,
        "items": [
            {**_profile(member), "status": row_status, "touchpoints": touchpoints.get(member.user_id, [])}
            for member, row_status in rows
        ],
        "next": f"{last.last_seen_at.isoformat()}_{last.user_id}" if last is not None else None,
    }


def parse_cursor(cursor: str) -> tuple[datetime.datetime, int] | None:
    """The (last_seen_at, user_id) a `next` names, or None if it names nothing."""
    seen_at, _, user_id = cursor.rpartition("_")
    try:
        return datetime.datetime.fromisoformat(seen_at), int(user_id)
    except ValueError:
        return None


async def person(db: AsyncSession, user_id: int) -> dict[str, Any] | None:
    row = (await db.execute(_members().where(AudienceMember.user_id == user_id))).first()
    if row is None:
        return None
    member, row_status = row
    touches = await db.scalars(
        select(AudienceTouch).where(AudienceTouch.user_id == user_id).order_by(AudienceTouch.first_at)
    )
    reach = await db.scalars(select(AudienceReach).where(AudienceReach.user_id == user_id))
    return {
        **_profile(member),
        "status": row_status,
        "is_premium": member.is_premium,
        "source": member.source,
        "opted_out_at": member.opted_out_at,
        "touches": [
            {"touchpoint": t.touchpoint, "first_at": t.first_at, "last_at": t.last_at, "count": t.count}
            for t in touches
        ],
        "reach": [{"bot": r.bot, "started_at": r.started_at, "blocked_at": r.blocked_at} for r in reach],
    }


def _profile(member: AudienceMember) -> dict[str, Any]:
    return {
        "user_id": member.user_id,
        "username": member.username,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "language_code": member.language_code,
        "first_seen_at": member.first_seen_at,
        "last_seen_at": member.last_seen_at,
    }


async def _touchpoints(db: AsyncSession, user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    used: dict[int, list[str]] = {}
    rows = await db.execute(
        select(AudienceTouch.user_id, AudienceTouch.touchpoint)
        .where(AudienceTouch.user_id.in_(user_ids))
        .order_by(AudienceTouch.first_at, AudienceTouch.touchpoint)
    )
    for user_id, touchpoint in rows:
        used.setdefault(user_id, []).append(touchpoint)
    return used
