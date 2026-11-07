"""What the console's «Использование» shows: who is in the app, for how long, where, and what they press.

Counted from `product_events` in this process rather than in SQL: sessions are
grouped in the database, and the rest (hours of the week in Prague, funnels in
order) is plain Python over what a month holds. That is a few thousand rows
now; if a month ever reaches millions, the sessions become a table of their own.
"""

from __future__ import annotations

import datetime
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db.models import ProductEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PERIODS = (1, 7, 30)
# The app says it is open this often (web/src/lib/track.ts); a session lasts
# from its first event to its last plus one beat.
HEARTBEAT = datetime.timedelta(seconds=30)
# «In the app now»: a beat within the last one and a bit, for a beat that is late.
ONLINE = datetime.timedelta(seconds=75)
# The zone the console reads in when it names none (docs/invariants.md: times are read where the reader is).
DEFAULT_ZONE = ZoneInfo("Europe/Prague")
TOP = 10
# Session lengths, in seconds: the console's bars, the last one open.
LENGTH_BINS = (30, 60, 180, 300, 600)

# What a tap is named by beside its event: the one property that says which.
_DETAIL = ("tab", "filter", "section", "from")
_NOT_TAPS = ("heartbeat", "screen_view", "session_start")


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    screen: str | None = None
    found: bool = False

    def matches(self, name: str, screen: str | None, props: dict[str, Any]) -> bool:
        if name != self.name or (self.screen is not None and screen != self.screen):
            return False
        return not self.found or int(props.get("results") or 0) > 0


# Each funnel counts people who took its steps in this order within the period.
FUNNELS: dict[str, tuple[Step, ...]] = {
    "find": (
        Step("opened", "session_start"),
        Step("searched", "search_submit"),
        Step("found", "search_submit", found=True),
        Step("helper", "helper_open"),
        Step("contact", "contact_tap"),
    ),
    "offer": (
        Step("opened", "session_start"),
        Step("offer", "offer_start"),
        Step("prices", "screen_view", screen="/offer/prices"),
    ),
    "chats": (
        Step("opened", "session_start"),
        Step("chats", "screen_view", screen="/chats"),
        Step("section", "screen_view", screen="/chats/:group"),
        Step("joined", "chat_open"),
    ),
}


def _local(at: datetime.datetime, zone: ZoneInfo) -> datetime.datetime:
    return at.replace(tzinfo=datetime.UTC).astimezone(zone)


def _hours(start: datetime.datetime, end: datetime.datetime, zone: ZoneInfo) -> set[tuple[int, int]]:
    """Each (weekday, hour) in `zone` that a session from `start` to `end` touched.

    Stepped in UTC and each hour converted: stepping the local clock would
    visit the hour that does not exist on the night the clocks go forward.
    """
    slots = set()
    # The start of the local hour, in UTC: a zone half an hour off UTC starts its hours at :30.
    local = _local(start, zone).replace(minute=0, second=0, microsecond=0)
    hour = local.astimezone(datetime.UTC).replace(tzinfo=None)
    while hour <= end:
        local = _local(hour, zone)
        slots.add((local.weekday(), local.hour))
        hour += datetime.timedelta(hours=1)
    return slots


def _funnel(
    steps: tuple[Step, ...], events: list[tuple[int, datetime.datetime, int, str, str | None, dict]]
) -> list[int]:
    """How many people reached each step, each after the one before.

    One event may take several steps: a search that found somebody is both
    «searched» and «found».
    """
    reached = [0] * len(steps)
    by_person: dict[int, list[tuple[datetime.datetime, int, str, str | None, dict]]] = defaultdict(list)
    for user_id, at, seq, name, screen, props in events:
        by_person[user_id].append((at, seq, name, screen, props or {}))
    for rows in by_person.values():
        step = 0
        # By the client's order too: a batch whose clock was off shares the server's arrival time.
        for _at, _seq, name, screen, props in sorted(rows, key=lambda row: (row[0], row[1])):
            while step < len(steps) and steps[step].matches(name, screen, props):
                reached[step] += 1
                step += 1
    return reached


async def usage(
    db: AsyncSession, *, days: int, now: datetime.datetime, zone: ZoneInfo = DEFAULT_ZONE
) -> dict[str, Any]:
    start = now - datetime.timedelta(days=days)
    in_period = ProductEvent.at >= start

    online = await db.scalar(
        select(func.count(func.distinct(ProductEvent.user_id))).where(ProductEvent.at >= now - ONLINE)
    )
    since = await db.scalar(select(func.min(ProductEvent.at)))

    sessions = (
        await db.execute(
            select(ProductEvent.user_id, func.min(ProductEvent.at), func.max(ProductEvent.at))
            .where(in_period)
            .group_by(ProductEvent.session, ProductEvent.user_id)
        )
    ).all()
    lengths = [(last - first + HEARTBEAT).total_seconds() for _user, first, last in sessions]

    by_day: dict[datetime.date, list[Any]] = {}
    heat: dict[tuple[int, int], set[int]] = defaultdict(set)
    for user_id, first, last in sessions:
        day = by_day.setdefault(_local(first, zone).date(), [0, set()])
        day[0] += 1
        day[1].add(user_id)
        for slot in _hours(first, last, zone):
            heat[slot].add(user_id)
    first_day = _local(start, zone).date()
    days_list = [first_day + datetime.timedelta(days=i) for i in range((_local(now, zone).date() - first_day).days + 1)]

    bins = [0] * (len(LENGTH_BINS) + 1)
    for seconds in lengths:
        bins[sum(seconds >= edge for edge in LENGTH_BINS)] += 1

    screens = (
        await db.execute(
            select(ProductEvent.screen, func.count(func.distinct(ProductEvent.user_id)).label("people"))
            .where(in_period, ProductEvent.name == "screen_view", ProductEvent.screen.is_not(None))
            .group_by(ProductEvent.screen)
            .order_by(func.count(func.distinct(ProductEvent.user_id)).desc(), ProductEvent.screen)
            .limit(TOP)
        )
    ).all()

    events = (
        await db.execute(
            select(
                ProductEvent.user_id,
                ProductEvent.at,
                ProductEvent.seq,
                ProductEvent.name,
                ProductEvent.screen,
                ProductEvent.props,
            ).where(in_period, ProductEvent.name != "heartbeat")
        )
    ).all()
    taps: Counter[tuple[str, str | None]] = Counter()
    entries: Counter[str] = Counter()
    for _user, _at, _seq, name, _screen, props in events:
        props = props or {}
        if name == "session_start":
            if not props.get("resumed"):
                entries[props.get("source") or ""] += 1
        elif name not in _NOT_TAPS:
            detail = next((str(props[key]) for key in _DETAIL if key in props), None)
            taps[(name, detail)] += 1
    rows = [tuple(row) for row in events]

    return {
        "days": days,
        "since": since,
        "online": online or 0,
        "people": len({user for user, _first, _last in sessions}),
        "sessions": len(sessions),
        "median_seconds": round(statistics.median(lengths)) if lengths else None,
        "by_day": [
            {
                "day": day,
                "sessions": by_day[day][0] if day in by_day else 0,
                "people": len(by_day[day][1]) if day in by_day else 0,
            }
            for day in days_list
        ],
        "heat": [
            {"weekday": weekday, "hour": hour, "people": len(people)}
            for (weekday, hour), people in sorted(heat.items())
        ],
        "lengths": [
            {
                "from_seconds": ([0, *LENGTH_BINS])[i],
                "to_seconds": (LENGTH_BINS[i] if i < len(LENGTH_BINS) else None),
                "sessions": n,
            }
            for i, n in enumerate(bins)
        ],
        "screens": [{"screen": screen, "people": people} for screen, people in screens],
        "taps": [{"name": name, "detail": detail, "count": n} for (name, detail), n in taps.most_common(TOP)],
        "funnels": [
            {
                "key": key,
                "steps": [{"key": step.key, "people": n} for step, n in zip(steps, _funnel(steps, rows), strict=True)],
            }
            for key, steps in FUNNELS.items()
        ],
        "entries": [{"source": source or None, "launches": n} for source, n in entries.most_common(TOP)],
    }
