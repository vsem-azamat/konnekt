"""The audience over time, for the console: four trends, the way from a chat to us, and where people came from.

Every number says who it counts (the console words it), and a day nothing was
recorded for is None, never 0: "nobody came" and "we were not counting yet"
must not look the same. Periods end yesterday, the last whole day; today is
apart, because half a day compared with whole ones reads as a fall.
"""

from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import func, literal, select, union_all

from app.audience.record import ESTIMATE
from app.audience.views import _members
from app.core.enums import Touchpoint
from app.db.models import (
    AudienceDay,
    AudienceMember,
    AudienceReach,
    AudienceTouch,
    Chat,
    ChatMember,
    JoinCaptcha,
    Message,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

Metric = Literal["starts", "app_new", "joins", "blocks"]
METRICS: tuple[Metric, ...] = ("starts", "app_new", "joins", "blocks")
PERIODS = (7, 30, 90)
# Past a month a bar is a week: 90 thin bars do not fit a phone.
WEEK_PAST = 30
# Segments show this many, and the rest as one row.
SEGMENT_ROWS = 5

# When each record began. Before that a day is unknown, not empty.
# The audience's own release (alembic e5d2a7c4b913): the first starts of the main bot.
STARTS_SINCE = datetime.date(2026, 10, 20)
# The catalog's first users, whom the backfill took as the Mini App's first opens.
APP_SINCE = datetime.date(2026, 7, 26)
# audience_days (alembic b8d4e1f6a2c7): blocks before it are known only while they stand.
DAYS_SINCE = datetime.date(2026, 11, 2)

# A request the bot let in: tapped the captcha, passed one elsewhere lately, or came from the catalog.
_LET_IN = (JoinCaptcha.STATUS_PASSED, JoinCaptcha.STATUS_TRUSTED, JoinCaptcha.STATUS_CATALOG)


def _day(value: Any) -> datetime.date:
    """A date as the database returns `date()`: a date on PostgreSQL, a string on SQLite."""
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])


def bars(days: int, today: datetime.date) -> list[tuple[datetime.date, datetime.date]]:
    """(first, last) day of each bar: the period before, then this one, the last ending yesterday."""
    step = 7 if days > WEEK_PAST else 1
    count = math.ceil(days / step) * 2
    last = today - datetime.timedelta(days=1)
    out = []
    for age in reversed(range(count)):
        end = last - datetime.timedelta(days=age * step)
        out.append((end - datetime.timedelta(days=step - 1), end))
    return out


async def _per_day(db: AsyncSession, metric: Metric, start: datetime.date) -> dict[datetime.date, int]:
    """How many of `metric` each day from `start` on."""
    since = datetime.datetime.combine(start, datetime.time())
    if metric == "starts":
        column = AudienceReach.started_at
        where: Iterable[Any] = (AudienceReach.bot == Touchpoint.MAIN_BOT, column >= since)
    elif metric == "app_new":
        column = AudienceTouch.first_at
        where = (AudienceTouch.touchpoint == Touchpoint.MINI_APP, column >= since)
    elif metric == "joins":
        column = JoinCaptcha.resolved_at
        where = (JoinCaptcha.status.in_(_LET_IN), column >= since)
    else:
        rows = await db.execute(
            select(AudienceDay.day, func.count())
            .where(
                AudienceDay.touchpoint == Touchpoint.MAIN_BOT,
                AudienceDay.event == "block",
                AudienceDay.day >= start,
            )
            .group_by(AudienceDay.day)
        )
        return {_day(day): count for day, count in rows}
    day = func.date(column)
    rows = await db.execute(select(day, func.count()).where(*where).group_by(day))
    return {_day(day): count for day, count in rows}


async def _since(db: AsyncSession) -> dict[Metric, datetime.date]:
    first_join = await db.scalar(select(func.min(JoinCaptcha.created_at)))
    return {
        "starts": STARTS_SINCE,
        "app_new": APP_SINCE,
        "joins": first_join.date() if first_join is not None else datetime.date.max,
        "blocks": DAYS_SINCE,
    }


def _value(counts: dict[datetime.date, int], first: datetime.date, last: datetime.date, since: datetime.date):
    """A bar's count, or None when none of it was counted. A bar counted only in part sums its counted days."""
    if last < since:
        return None
    day, total = max(first, since), 0
    while day <= last:
        total += counts.get(day, 0)
        day += datetime.timedelta(days=1)
    return total


def _total(values: list[int | None]) -> int | None:
    counted = [v for v in values if v is not None]
    return sum(counted) if counted else None


def _chat_people() -> Any:
    """(user_id, chat_id, at) for each time the bot saw somebody in a chat: wrote, asked to join, or is a member."""
    return union_all(
        select(Message.user_id, Message.chat_id, Message.timestamp.label("at")),
        select(JoinCaptcha.user_id, JoinCaptcha.chat_id, JoinCaptcha.created_at.label("at")),
        select(ChatMember.user_id, ChatMember.chat_id, ChatMember.changed_at.label("at")),
    ).subquery()


async def trends(db: AsyncSession, *, days: int, today: datetime.date) -> dict[str, Any]:
    spans = bars(days, today)
    since = await _since(db)
    start = spans[0][0]
    series: list[dict[str, Any]] = [{"from": first, "to": last} for first, last in spans]
    now_point: dict[str, Any] = {"from": today, "to": today}
    for metric in METRICS:
        counts = await _per_day(db, metric, min(start, today))
        for point, (first, last) in zip(series, spans, strict=True):
            point[metric] = _value(counts, first, last, since[metric])
        now_point[metric] = _value(counts, today, today, since[metric])
    half = len(series) // 2
    totals = {
        metric: {
            "now": _total([p[metric] for p in series[half:]]),
            "before": _total([p[metric] for p in series[:half]]),
        }
        for metric in METRICS
    }
    period_start = datetime.datetime.combine(series[half]["from"], datetime.time())
    return {
        "days": days,
        "today": today,
        "counted_since": {metric: since[metric] if since[metric] != datetime.date.max else today for metric in METRICS},
        "series": series,
        "today_point": now_point,
        "totals": totals,
        **await _funnel(db, period_start),
        "segments": await _segments(db),
    }


def _came() -> Any:
    """Everybody who started the main bot or opened the Mini App."""
    return union_all(
        select(AudienceReach.user_id).where(
            AudienceReach.bot == Touchpoint.MAIN_BOT, AudienceReach.started_at.is_not(None)
        ),
        select(AudienceTouch.user_id).where(AudienceTouch.touchpoint == Touchpoint.MINI_APP),
    ).subquery()


async def _funnel(db: AsyncSession, period_start: datetime.datetime) -> dict[str, Any]:
    seen = _chat_people()
    in_chats = select(seen.c.user_id)
    came = select(_came().c.user_id).distinct().subquery()

    started = (
        select(AudienceReach.user_id)
        .where(AudienceReach.bot == Touchpoint.MAIN_BOT, AudienceReach.started_at.is_not(None))
        .subquery()
    )
    opened = select(AudienceTouch.user_id).where(AudienceTouch.touchpoint == Touchpoint.MINI_APP).subquery()

    members = _members().subquery()
    statuses: dict[str, int] = {}
    for status, people in await db.execute(select(members.c.status, func.count()).group_by(members.c.status)):
        statuses[status] = people

    async def count(statement: Any) -> int:
        return await db.scalar(select(func.count()).select_from(statement.subquery())) or 0

    return {
        "funnel": {
            "seen_in_chats": await count(select(seen.c.user_id).distinct()),
            "started_bot": await count(select(started.c.user_id)),
            "opened_app": await count(select(opened.c.user_id)),
            "both": await count(select(started.c.user_id).where(started.c.user_id.in_(select(opened.c.user_id)))),
            "not_from_chats": await count(select(came.c.user_id).where(came.c.user_id.not_in(in_chats))),
            "reachable": statuses.get("reachable", 0),
            "blocked": statuses.get("blocked", 0),
            "opted_out": statuses.get("opted_out", 0),
            "estimate": await count(
                select(AudienceMember.user_id).where(
                    AudienceMember.source == ESTIMATE, AudienceMember.user_id.not_in(select(came.c.user_id))
                )
            ),
        },
        # Not who was first seen in a chat: members are known only since the bot began asking, so all would look new.
        "funnel_new": {
            "started_bot": await count(
                select(AudienceReach.user_id).where(
                    AudienceReach.bot == Touchpoint.MAIN_BOT, AudienceReach.started_at >= period_start
                )
            ),
            "opened_app": await count(
                select(AudienceTouch.user_id).where(
                    AudienceTouch.touchpoint == Touchpoint.MINI_APP, AudienceTouch.first_at >= period_start
                )
            ),
        },
    }


def _fold(rows: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """The largest few, and the rest as one row keyed «other» with how many they are."""
    rows = sorted(rows, key=lambda row: (-row[2], row[1]))
    out = [{"key": key, "label": label, "people": people} for key, label, people in rows[:SEGMENT_ROWS]]
    rest = rows[SEGMENT_ROWS:]
    if rest:
        out.append({"key": "other", "label": str(len(rest)), "people": sum(row[2] for row in rest)})
    return out


async def _segments(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Who came to us, by the chat the bot saw them in first, their Telegram language, and the link that brought them."""
    came = select(_came().c.user_id).distinct().subquery()
    seen = _chat_people()
    ranked = (
        select(
            seen.c.user_id,
            seen.c.chat_id,
            func.row_number().over(partition_by=seen.c.user_id, order_by=(seen.c.at, seen.c.chat_id)).label("rank"),
        )
        .where(seen.c.user_id.in_(select(came.c.user_id)))
        .subquery()
    )
    chats = await db.execute(
        select(ranked.c.chat_id, func.coalesce(Chat.title, literal("")), func.count())
        .outerjoin(Chat, Chat.id == ranked.c.chat_id)
        .where(ranked.c.rank == 1)
        .group_by(ranked.c.chat_id, Chat.title)
    )
    profile = select(AudienceMember).where(AudienceMember.user_id.in_(select(came.c.user_id))).subquery()
    languages = await db.execute(
        select(func.coalesce(profile.c.language_code, literal("")), func.count()).group_by(profile.c.language_code)
    )
    sources = await db.execute(
        select(func.coalesce(profile.c.source, literal("")), func.count()).group_by(profile.c.source)
    )
    return {
        "chats": _fold([(str(chat_id), title or str(chat_id), people) for chat_id, title, people in chats]),
        "languages": _fold([(code, code, people) for code, people in languages]),
        "sources": _fold([(source, source, people) for source, people in sources]),
    }
