"""Which days each person used each touchpoint, and the days a bot was blocked or let back in."""

import datetime

import pytest
from app.audience import record
from app.audience.record import Person, Touchpoint
from app.db.models import AudienceDay
from sqlalchemy import select

pytestmark = pytest.mark.unit

MORNING = datetime.datetime(2026, 11, 2, 8, 0)
EVENING = datetime.datetime(2026, 11, 2, 21, 30)
NEXT_DAY = datetime.datetime(2026, 11, 3, 9, 15)

ANNA = Person(id=51234, username="anna_n", first_name="Anna")


async def _days(session_maker, user_id=ANNA.id):
    async with session_maker() as db:
        rows = await db.scalars(
            select(AudienceDay)
            .where(AudienceDay.user_id == user_id)
            .order_by(AudienceDay.day, AudienceDay.touchpoint, AudienceDay.event)
        )
        return [(row.day.isoformat(), row.touchpoint, row.event) for row in rows]


async def test_a_day_is_written_once_however_many_visits_it_has(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=MORNING)
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=EVENING)
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=EVENING)
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=NEXT_DAY)
        await db.commit()

    assert await _days(session_maker) == [
        ("2026-11-02", "main_bot", "visit"),
        ("2026-11-02", "mini_app", "visit"),
        ("2026-11-03", "mini_app", "visit"),
    ]


async def test_a_replayed_visit_leaves_its_day(session_maker):
    """The backfill replays what really happened: that day was a visit, though it adds nothing to the count."""
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.CONTACT_BOT, at=MORNING, replay=True)
        await db.commit()

    assert await _days(session_maker) == [("2026-11-02", "contact_bot", "visit")]


async def test_a_block_and_an_unblock_are_days_of_the_bot(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=MORNING, started=Touchpoint.MAIN_BOT)
        await record.blocked(db, ANNA.id, Touchpoint.MAIN_BOT, at=EVENING)
        await record.started(db, ANNA.id, Touchpoint.MAIN_BOT, at=NEXT_DAY)
        await db.commit()

    assert await _days(session_maker) == [
        ("2026-11-02", "main_bot", "block"),
        ("2026-11-02", "main_bot", "visit"),
        ("2026-11-03", "main_bot", "unblock"),
    ]


async def test_a_send_refused_again_is_not_another_block(session_maker):
    """Every send to somebody who blocked the bot ends in a 403; only the first is news."""
    async with session_maker() as db:
        await record.blocked(db, ANNA.id, Touchpoint.MAIN_BOT, at=MORNING)
        await record.blocked(db, ANNA.id, Touchpoint.MAIN_BOT, at=NEXT_DAY)
        await db.commit()

    assert await _days(session_maker) == [("2026-11-02", "main_bot", "block")]


async def test_a_start_that_lifts_no_block_is_not_an_unblock(session_maker):
    async with session_maker() as db:
        await record.started(db, ANNA.id, Touchpoint.MAIN_BOT, at=MORNING)
        await db.commit()

    assert await _days(session_maker) == []


async def test_bots_leave_no_days(session_maker):
    bot = Person(id=999, username="some_bot", first_name="Bot", is_bot=True)
    async with session_maker() as db:
        await record.seen(db, bot, Touchpoint.MAIN_BOT, at=MORNING)
        await db.commit()

    assert await _days(session_maker, user_id=999) == []
