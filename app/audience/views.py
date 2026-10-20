"""Reading the audience for the console: the summary, a filtered page, one person.

A person's status is about the main bot, the one any announcement would come
from, and the four statuses do not overlap: opting out outranks a block,
which outranks having started the bot.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import case, func, or_, select

from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch

if TYPE_CHECKING:
    import datetime

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


async def summary(db: AsyncSession, *, now: datetime.datetime) -> dict[str, Any]:
    # Counted in Python over every member: the audience is thousands of rows,
    # and one pass answers four questions that would otherwise be four queries.
    rows = (await db.execute(_members())).all()
    counted = Counter(status for _, status in rows)
    # Every status named, a zero too: adding Counters would drop it.
    reach = {status: counted[status] for status in STATUSES}

    # The touchpoint each person used first; a tie, as the backfill can leave, is broken by name.
    first = (
        select(
            AudienceTouch.user_id,
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

    # Weeks counted back from now, not calendar weeks: the last bar is always the latest seven days.
    new_by_week = [0] * WEEKS
    for member, _ in rows:
        age = (now - member.first_seen_at).days // 7
        if 0 <= age < WEEKS:
            new_by_week[WEEKS - 1 - age] += 1

    languages = Counter(member.language_code for member, _ in rows if member.language_code)
    return {
        "total": len(rows),
        "reach": reach,
        "first_touch": first_touch,
        "new_by_week": new_by_week,
        "new_this_week": new_by_week[-1],
        "languages": [
            {"code": code, "count": count}
            for code, count in sorted(languages.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


async def page(
    db: AsyncSession,
    *,
    touchpoint: Touchpoint | None = None,
    status: Status | None = None,
    language: str | None = None,
    query: str | None = None,
    first_seen_after: datetime.datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Members newest activity first, with the touchpoints each has used."""
    statement = _members()
    if touchpoint is not None:
        used = select(AudienceTouch.user_id).where(AudienceTouch.touchpoint == touchpoint)
        statement = statement.where(AudienceMember.user_id.in_(used))
    if status is not None:
        statement = statement.where(_status == status)
    if language is not None:
        statement = statement.where(AudienceMember.language_code == language)
    if first_seen_after is not None:
        statement = statement.where(AudienceMember.first_seen_at >= first_seen_after)
    if query := (query or "").strip().removeprefix("@"):
        like = f"%{query}%"
        matches = [
            AudienceMember.username.ilike(like),
            AudienceMember.first_name.ilike(like),
            AudienceMember.last_name.ilike(like),
        ]
        if query.isdigit():
            matches.append(AudienceMember.user_id == int(query))
        statement = statement.where(or_(*matches))

    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = (
        await db.execute(
            statement.order_by(AudienceMember.last_seen_at.desc(), AudienceMember.user_id).limit(limit).offset(offset)
        )
    ).all()
    touchpoints = await _touchpoints(db, [member.user_id for member, _ in rows])
    return {
        "total": total or 0,
        "items": [
            {**_profile(member), "status": row_status, "touchpoints": touchpoints.get(member.user_id, [])}
            for member, row_status in rows
        ],
    }


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
