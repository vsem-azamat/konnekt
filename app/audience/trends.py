"""The audience over time, for the console: four trends, the way from a chat to us, where people came from, and the Overview's few numbers.

Every number says who it counts (the console words it), and a day nothing was
recorded for is None, never 0: "nobody came" and "we were not counting yet"
must not look the same. Periods end yesterday, the last whole day; today is
apart, because half a day compared with whole ones reads as a fall.
"""

from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import exists, func, literal, or_, select, union, union_all

from app.audience.record import ESTIMATE
from app.audience.views import _members
from app.core.enums import Touchpoint
from app.db.models import (
    AdsTopic,
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
# Segments show this many, and the rest as one row under a key no link can carry (see record.SOURCE).
SEGMENT_ROWS = 5
REST = "*"

# When each record began. Before that a day is unknown, not empty.
# The audience's own release (alembic e5d2a7c4b913): the first starts of the main bot.
STARTS_SINCE = datetime.date(2026, 10, 20)
# The catalog's first users, whom the backfill took as the Mini App's first opens.
APP_SINCE = datetime.date(2026, 7, 26)
# audience_days (alembic b8d4e1f6a2c7): blocks before it are known only while they stand.
DAYS_SINCE = datetime.date(2026, 11, 2)

# The Overview compares a week with the week before it.
WEEK = 7

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
    """A bar's count, or None unless all of it was recorded: a week recorded for two days would read as a quiet week."""
    if first < since:
        return None
    day, total = first, 0
    while day <= last:
        total += counts.get(day, 0)
        day += datetime.timedelta(days=1)
    return total


def _total(counts: dict[datetime.date, int], first: datetime.date, last: datetime.date, since: datetime.date):
    """A period's sum over the days recorded in it, or None if none were.

    By day, not by bar: a week recorded only in part is hatched on the chart,
    yet its recorded days still belong to the period's total.
    """
    if last < since:
        return None
    day, total = max(first, since), 0
    while day <= last:
        total += counts.get(day, 0)
        day += datetime.timedelta(days=1)
    return total


def _in_chats(user_id: Any) -> Any:
    """Whether the bot saw `user_id` in a chat: wrote there (messages are kept 180 days), asked to join, or is a member.

    EXISTS on each table rather than IN over their union: messages grow past
    what PostgreSQL will hash, and NOT IN then rescans them for every person.
    """
    return or_(
        exists().where(Message.user_id == user_id),
        exists().where(JoinCaptcha.user_id == user_id),
        exists().where(ChatMember.user_id == user_id),
    )


async def trends(db: AsyncSession, *, days: int, today: datetime.date) -> dict[str, Any]:
    spans = bars(days, today)
    since = await _since(db)
    start = spans[0][0]
    series: list[dict[str, Any]] = [{"from": first, "to": last} for first, last in spans]
    now_point: dict[str, Any] = {"from": today, "to": today}
    half = len(series) // 2
    totals: dict[str, dict[str, int | None]] = {}
    for metric in METRICS:
        counts = await _per_day(db, metric, min(start, today))
        for point, (first, last) in zip(series, spans, strict=True):
            point[metric] = _value(counts, first, last, since[metric])
        now_point[metric] = _value(counts, today, today, since[metric])
        totals[metric] = {
            "now": _total(counts, series[half]["from"], series[-1]["to"], since[metric]),
            "before": _total(counts, series[0]["from"], series[half - 1]["to"], since[metric]),
        }
    period = (
        datetime.datetime.combine(series[half]["from"], datetime.time()),
        datetime.datetime.combine(today, datetime.time()),
    )
    return {
        "days": days,
        "today": today,
        "counted_since": {metric: since[metric] if since[metric] != datetime.date.max else today for metric in METRICS},
        "series": series,
        "today_point": now_point,
        "totals": totals,
        **await _funnel(db, period),
        "segments": await _segments(db),
    }


def _came() -> Any:
    """Everybody the main bot may have written to at some point, or who opened the Mini App.

    The reach's ``started_at`` is the first leave the main bot had to write:
    a /start, any private message, or the Mini App's permission. Not only Start.
    """
    return union_all(
        select(AudienceReach.user_id, AudienceReach.started_at.label("at")).where(
            AudienceReach.bot == Touchpoint.MAIN_BOT, AudienceReach.started_at.is_not(None)
        ),
        select(AudienceTouch.user_id, AudienceTouch.first_at.label("at")).where(
            AudienceTouch.touchpoint == Touchpoint.MINI_APP
        ),
    ).subquery()


async def _funnel(db: AsyncSession, period: tuple[datetime.datetime, datetime.datetime]) -> dict[str, Any]:
    came = select(_came().c.user_id).distinct().subquery()
    started = (
        select(AudienceReach.user_id)
        .where(AudienceReach.bot == Touchpoint.MAIN_BOT, AudienceReach.started_at.is_not(None))
        .subquery()
    )
    opened = select(AudienceTouch.user_id).where(AudienceTouch.touchpoint == Touchpoint.MINI_APP).subquery()
    seen = union(select(Message.user_id).distinct(), select(JoinCaptcha.user_id), select(ChatMember.user_id)).subquery()
    # Confirmed in any way at all: any leave to write, or any touchpoint but the guessed one.
    confirmed = or_(
        exists().where(AudienceReach.user_id == AudienceMember.user_id, AudienceReach.started_at.is_not(None)),
        exists().where(
            AudienceTouch.user_id == AudienceMember.user_id, AudienceTouch.touchpoint != Touchpoint.MAIN_BOT
        ),
    )

    members = _members().subquery()
    statuses: dict[str, int] = {}
    for status, people in await db.execute(select(members.c.status, func.count()).group_by(members.c.status)):
        statuses[status] = people

    async def count(statement: Any) -> int:
        return await db.scalar(select(func.count()).select_from(statement.subquery())) or 0

    start, end = period
    return {
        "funnel": {
            "seen_in_chats": await count(select(seen.c.user_id)),
            "started_bot": await count(select(started.c.user_id)),
            "opened_app": await count(select(opened.c.user_id)),
            "both": await count(select(started.c.user_id).where(started.c.user_id.in_(select(opened.c.user_id)))),
            "not_from_chats": await count(select(came.c.user_id).where(~_in_chats(came.c.user_id))),
            "reachable": statuses.get("reachable", 0),
            "blocked": statuses.get("blocked", 0),
            "opted_out": statuses.get("opted_out", 0),
            "estimate": await count(
                select(AudienceMember.user_id).where(AudienceMember.source == ESTIMATE, ~confirmed)
            ),
        },
        # The bars' period, to yesterday. Not who was first seen in a chat: members
        # are known only since the bot began asking, so all would look new.
        "funnel_new": {
            "started_bot": await count(
                select(AudienceReach.user_id).where(
                    AudienceReach.bot == Touchpoint.MAIN_BOT,
                    AudienceReach.started_at >= start,
                    AudienceReach.started_at < end,
                )
            ),
            "opened_app": await count(
                select(AudienceTouch.user_id).where(
                    AudienceTouch.touchpoint == Touchpoint.MINI_APP,
                    AudienceTouch.first_at >= start,
                    AudienceTouch.first_at < end,
                )
            ),
        },
    }


def _fold(rows: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """The largest few, and the rest as one row keyed `REST` with how many they are."""
    rows = sorted(rows, key=lambda row: (-row[2], row[1]))
    out = [{"key": key, "label": label, "people": people} for key, label, people in rows[:SEGMENT_ROWS]]
    rest = rows[SEGMENT_ROWS:]
    if rest:
        out.append({"key": REST, "label": str(len(rest)), "people": sum(row[2] for row in rest)})
    return out


async def _segments(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Who came to us, by the chat the bot saw them write or ask to join in first, their Telegram language, and their first link."""
    came = select(_came().c.user_id).distinct().subquery()
    # Where the bot saw them write or ask to join; a membership's date is its last change, not the first sight.
    who = select(came.c.user_id)
    seen = union_all(
        select(Message.user_id, Message.chat_id, Message.timestamp.label("at")).where(Message.user_id.in_(who)),
        select(JoinCaptcha.user_id, JoinCaptcha.chat_id, JoinCaptcha.created_at.label("at")).where(
            JoinCaptcha.user_id.in_(who)
        ),
    ).subquery()
    ranked = (
        select(
            seen.c.user_id,
            seen.c.chat_id,
            func.row_number().over(partition_by=seen.c.user_id, order_by=(seen.c.at, seen.c.chat_id)).label("rank"),
        )
    ).subquery()
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


async def overview(db: AsyncSession, *, today: datetime.date) -> dict[str, Any]:
    """The console's Overview: who came to us, this week's newcomers against the week before, and each bot's reach.

    "Came" is the Audience page's: gave the main bot leave to write or opened
    the Mini App, so the backfill's guesses are out. Weeks are whole days to
    yesterday, as the bars are; a week before the starts were recorded is not
    compared, since everyone who used the bot earlier was dated to their first
    start after it. A guess who writes to the bot later is in the total but in
    no week: they were here before, whenever they come back.
    """
    came = _came()
    first = select(came.c.user_id, func.min(came.c.at).label("at")).group_by(came.c.user_id).subquery()
    # The source is never overwritten, so a guess stays one after they come.
    guessed = select(AudienceMember.user_id).where(AudienceMember.source == ESTIMATE)

    def midnight(day: datetime.date) -> datetime.datetime:
        return datetime.datetime.combine(day, datetime.time())

    async def came_between(start: datetime.date, end: datetime.date) -> int | None:
        if start < STARTS_SINCE:
            return None
        new = (first.c.at >= midnight(start), first.c.at < midnight(end), first.c.user_id.not_in(guessed))
        return await db.scalar(select(func.count()).where(*new)) or 0

    week = datetime.timedelta(days=WEEK)
    members = _members().subquery()
    statuses: dict[str, int] = {}
    for status, people in await db.execute(select(members.c.status, func.count()).group_by(members.c.status)):
        statuses[status] = people

    async def touched(touchpoint: Touchpoint) -> int:
        return await db.scalar(select(func.count()).where(AudienceTouch.touchpoint == touchpoint)) or 0

    return {
        "came": {
            "total": await db.scalar(select(func.count()).select_from(first)) or 0,
            "now": await came_between(today - week, today),
            "before": await came_between(today - 2 * week, today - week),
            "compare_from": STARTS_SINCE + 2 * week,
        },
        "main_bot": {status: statuses.get(status, 0) for status in ("reachable", "blocked", "opted_out")},
        "contact_bot": {
            "wrote": await touched(Touchpoint.CONTACT_BOT),
            "blocked": await db.scalar(
                select(func.count()).where(
                    AudienceReach.bot == Touchpoint.CONTACT_BOT, AudienceReach.blocked_at.is_not(None)
                )
            )
            or 0,
            # Each has a topic in the staff group, and one more if the desk moved groups.
            "ads_conversations": await db.scalar(select(func.count(AdsTopic.user_id.distinct()))) or 0,
        },
        "moved_bot": await touched(Touchpoint.MOVED_BOT),
    }
