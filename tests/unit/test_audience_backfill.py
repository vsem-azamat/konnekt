"""The one-off fill of the audience from what was recorded before it existed."""

import datetime

import pytest
from app.audience import backfill
from app.audience.backfill import CatalogUser
from app.core.enums import Touchpoint
from app.db.models import (
    AdsTopic,
    AudienceMember,
    AudienceReach,
    AudienceTouch,
    Message,
    ModerationEvent,
    SpamPing,
    User,
)
from sqlalchemy import select

pytestmark = pytest.mark.unit

T0 = datetime.datetime(2026, 1, 12, 9, 0)
T1 = datetime.datetime(2026, 10, 19, 18, 0)
UTC = datetime.UTC


async def _touches(session_maker) -> set[tuple[int, str]]:
    async with session_maker() as db:
        return {(t.user_id, t.touchpoint) for t in await db.scalars(select(AudienceTouch))}


async def test_everyone_who_wrote_to_the_contact_bot(session_maker):
    async with session_maker() as db:
        topic = AdsTopic(group_id=-100555, user_id=21, thread_id=7)
        topic.created_at = T0
        db.add(topic)
        await db.commit()

    assert await backfill.from_contact_desk(session_maker) == 1

    assert await _touches(session_maker) == {(21, Touchpoint.CONTACT_BOT)}
    async with session_maker() as db:
        reach = await db.get(AudienceReach, (21, Touchpoint.CONTACT_BOT))
        member = await db.get(AudienceMember, 21)
    assert reach.started_at == T0
    assert member.first_seen_at == T0


async def test_catalog_users_with_their_reach_and_opt_out(session_maker):
    olena_row = CatalogUser(
        tg_id=31,
        username="olena",
        first_name="Olena",
        last_name=None,
        source="matfyz",
        created_at=T0.replace(tzinfo=UTC),
        last_seen_at=T1.replace(tzinfo=UTC),
        bot_started_at=T0.replace(tzinfo=UTC),
        unsubscribed_at=None,
    )
    petr_row = CatalogUser(
        tg_id=32,
        username=None,
        first_name="Petr",
        last_name="D.",
        source=None,
        created_at=T0.replace(tzinfo=UTC),
        last_seen_at=None,
        bot_started_at=None,
        unsubscribed_at=T1.replace(tzinfo=UTC),
    )

    assert await backfill.from_catalog(session_maker, [olena_row, petr_row]) == 2

    assert await _touches(session_maker) == {
        (31, Touchpoint.MINI_APP),
        # The catalog's bot_started_at came from the retired bots' Mini App.
        (31, Touchpoint.MOVED_BOT),
        (32, Touchpoint.MINI_APP),
    }
    async with session_maker() as db:
        olena = await db.get(AudienceMember, 31)
        petr = await db.get(AudienceMember, 32)
        reach = list(await db.scalars(select(AudienceReach)))
    assert (olena.username, olena.source, olena.first_seen_at, olena.last_seen_at) == ("olena", "matfyz", T0, T1)
    # Neither says anything about the main bot.
    assert reach == []
    assert petr.opted_out_at == T1
    assert petr.last_seen_at == T0


async def test_a_private_contact_with_the_main_bot_is_estimated_and_labelled(session_maker):
    """`users` holds group members too; whoever left no trace in a group or in moderation is the estimate."""
    async with session_maker() as db:
        people = [
            User(id=41, first_name="Private", username="only_dm"),
            User(id=42, first_name="Talker"),
            User(id=43, first_name="Banned", blocked=True),
            User(id=44, first_name="Pinged"),
            User(id=45, first_name="Moderated"),
            User(id=-1001, first_name="A channel"),
        ]
        for person in people:
            person.created_at = backfill.ESTIMATE_BEFORE - datetime.timedelta(days=1)
        # Recorded since people who never wrote are: a joiner, not a private contact.
        joiner = User(id=46, first_name="Joiner")
        joiner.created_at = backfill.ESTIMATE_BEFORE
        db.add_all([*people, joiner])
        db.add(Message(chat_id=-100777, user_id=42, message_id=1, message="hi"))
        db.add(SpamPing(chat_id=-100777, user_id=44, message_id=2, kind="ad", matches=[], detected_at=T0))
        db.add(ModerationEvent(action="ban", source="command", actor_id=1, target_user_id=45, chat_id=-100777))
        await db.commit()

    assert await backfill.from_bot_users(session_maker) == 1

    assert await _touches(session_maker) == {(41, Touchpoint.MAIN_BOT)}
    async with session_maker() as db:
        member = await db.get(AudienceMember, 41)
        reach = list(await db.scalars(select(AudienceReach)))
    assert (member.username, member.source) == ("only_dm", backfill.ESTIMATE)
    # Not confirmed until the person writes again.
    assert reach == []


async def test_running_it_twice_adds_nothing(session_maker):
    async with session_maker() as db:
        db.add(AdsTopic(group_id=-100555, user_id=21, thread_id=7))
        await db.commit()

    for _ in range(2):
        await backfill.from_contact_desk(session_maker)

    async with session_maker() as db:
        touch = await db.get(AudienceTouch, (21, Touchpoint.CONTACT_BOT))
    assert touch.count == 1


async def test_the_estimate_never_touches_someone_already_known(session_maker):
    from app.audience import record
    from app.audience.record import Person

    async with session_maker() as db:
        db.add(User(id=41, first_name="Known"))
        await record.seen(db, Person(id=41, first_name="Known"), Touchpoint.MINI_APP, at=T1)
        await db.commit()

    assert await backfill.from_bot_users(session_maker) == 0

    async with session_maker() as db:
        member = await db.get(AudienceMember, 41)
    assert (member.source, member.first_seen_at) == (None, T1)


async def test_live_profile_survives_the_backfill(session_maker):
    from app.audience import record
    from app.audience.record import Person

    async with session_maker() as db:
        await record.seen(
            db, Person(id=21, first_name="Live", language_code="uk", is_premium=True), Touchpoint.MAIN_BOT, at=T0
        )
        db.add(AdsTopic(group_id=-100555, user_id=21, thread_id=7))
        await db.commit()

    await backfill.from_contact_desk(session_maker)

    async with session_maker() as db:
        member = await db.get(AudienceMember, 21)
    assert (member.first_name, member.language_code, member.is_premium) == ("Live", "uk", True)


def test_the_catalog_address_comes_in_on_stdin_and_never_as_an_argument():
    """An argument shows in `ps` and in shell history; the address holds the catalog's password."""
    import io

    assert backfill.catalog_dsn(io.StringIO("postgresql+asyncpg://u:secret@catalog-postgres:5432/db\n")) == (
        "postgresql+asyncpg://u:secret@catalog-postgres:5432/db"
    )
    with pytest.raises(SystemExit):
        backfill.catalog_dsn(io.StringIO(""))


def test_the_command_line_has_no_place_for_the_address():
    with pytest.raises(SystemExit):
        backfill.arguments(["--catalog-dsn", "postgresql://x"])
    assert backfill.arguments(["--catalog-from-stdin"]).catalog_from_stdin is True
    assert backfill.arguments([]).catalog_from_stdin is False
