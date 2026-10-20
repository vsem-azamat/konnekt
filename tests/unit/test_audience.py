"""Who has ever used our bots or the Mini App, and whether a bot may still write to them."""

import datetime

import pytest
from app.audience import record
from app.audience.record import Person, Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from sqlalchemy import select

pytestmark = pytest.mark.unit

T0 = datetime.datetime(2026, 3, 3, 10, 11)
T1 = datetime.datetime(2026, 10, 20, 14, 2)

ANNA = Person(id=51234, username="anna_n", first_name="Anna", last_name="N.", language_code="ru", is_premium=True)


async def _member(session_maker, user_id=ANNA.id):
    async with session_maker() as db:
        return await db.get(AudienceMember, user_id)


async def _touches(session_maker, user_id=ANNA.id):
    async with session_maker() as db:
        rows = await db.scalars(select(AudienceTouch).where(AudienceTouch.user_id == user_id))
        return {row.touchpoint: row for row in rows}


async def _reach(session_maker, bot, user_id=ANNA.id):
    async with session_maker() as db:
        return await db.get(AudienceReach, (user_id, bot))


async def test_first_visit_creates_the_member_with_what_telegram_gave(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0)
        await db.commit()

    member = await _member(session_maker)
    assert (member.username, member.first_name, member.last_name) == ("anna_n", "Anna", "N.")
    assert (member.language_code, member.is_premium) == ("ru", True)
    assert member.first_seen_at == T0
    assert member.last_seen_at == T0
    assert member.opted_out_at is None


async def test_later_visit_moves_last_seen_and_keeps_first_seen(session_maker):
    renamed = Person(id=ANNA.id, username="anna", first_name="Anna", last_name=None, language_code="cs")
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0)
        await record.seen(db, renamed, Touchpoint.MINI_APP, at=T1)
        await db.commit()

    member = await _member(session_maker)
    assert member.first_seen_at == T0
    assert member.last_seen_at == T1
    assert (member.username, member.last_name, member.language_code) == ("anna", None, "cs")


async def test_each_touchpoint_keeps_its_own_first_last_and_count(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0)
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T1)
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=T1)
        await db.commit()

    touches = await _touches(session_maker)
    assert set(touches) == {Touchpoint.MAIN_BOT, Touchpoint.MINI_APP}
    main = touches[Touchpoint.MAIN_BOT]
    assert (main.first_at, main.last_at, main.count) == (T0, T1, 2)
    assert touches[Touchpoint.MINI_APP].count == 1


async def test_an_older_event_does_not_pull_last_seen_back(session_maker):
    """The backfill replays history after live traffic has already been recorded."""
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T1)
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0)
        await db.commit()

    member = await _member(session_maker)
    assert (member.first_seen_at, member.last_seen_at) == (T0, T1)
    main = (await _touches(session_maker))[Touchpoint.MAIN_BOT]
    assert (main.first_at, main.last_at) == (T0, T1)


async def test_the_first_source_wins(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MINI_APP, at=T0, source="matfyz")
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T1, source="vut")
        await db.commit()

    assert (await _member(session_maker)).source == "matfyz"


async def test_writing_to_a_bot_means_that_bot_may_write_back(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.CONTACT_BOT, at=T0, started=Touchpoint.CONTACT_BOT)
        await db.commit()

    reach = await _reach(session_maker, Touchpoint.CONTACT_BOT)
    assert (reach.started_at, reach.blocked_at) == (T0, None)
    assert await _reach(session_maker, Touchpoint.MAIN_BOT) is None


async def test_blocking_and_unblocking_the_bot(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0, started=Touchpoint.MAIN_BOT)
        await record.blocked(db, ANNA.id, Touchpoint.MAIN_BOT, at=T1)
        await db.commit()
    reach = await _reach(session_maker, Touchpoint.MAIN_BOT)
    assert (reach.started_at, reach.blocked_at) == (T0, T1)

    later = T1 + datetime.timedelta(days=1)
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=later, started=Touchpoint.MAIN_BOT)
        await db.commit()
    reach = await _reach(session_maker, Touchpoint.MAIN_BOT)
    assert (reach.started_at, reach.blocked_at) == (T0, None)


async def test_a_block_is_kept_even_for_someone_not_seen_before(session_maker):
    """A 403 can come before anything else about the person was recorded."""
    async with session_maker() as db:
        await record.blocked(db, 777, Touchpoint.CONTACT_BOT, at=T1)
        await db.commit()

    reach = await _reach(session_maker, Touchpoint.CONTACT_BOT, user_id=777)
    assert (reach.started_at, reach.blocked_at) == (None, T1)


async def test_bots_never_join_the_audience(session_maker):
    bot = Person(id=999, username="some_bot", first_name="Bot", is_bot=True)
    async with session_maker() as db:
        await record.seen(db, bot, Touchpoint.MAIN_BOT, at=T0)
        await db.commit()

    assert await _member(session_maker, 999) is None


async def test_opting_out_is_kept_and_a_new_visit_does_not_undo_it(session_maker):
    async with session_maker() as db:
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0)
        await record.opted_out(db, ANNA.id, at=T0)
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T1)
        await db.commit()

    assert (await _member(session_maker)).opted_out_at == T0


async def test_a_replayed_older_visit_does_not_lift_a_newer_block(session_maker):
    async with session_maker() as db:
        await record.blocked(db, ANNA.id, Touchpoint.MAIN_BOT, at=T1)
        await record.seen(db, ANNA, Touchpoint.MAIN_BOT, at=T0, started=Touchpoint.MAIN_BOT, replay=True)
        await record.started(db, ANNA.id, Touchpoint.MAIN_BOT, at=T0)
        await db.commit()

    reach = await _reach(session_maker, Touchpoint.MAIN_BOT)
    assert (reach.started_at, reach.blocked_at) == (T0, T1)
