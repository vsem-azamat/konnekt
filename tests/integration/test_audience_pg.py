"""The audience upserts, on PostgreSQL.

They are written once for both dialects (`app.db.upsert`), and the order
rules live in CASE expressions over ``excluded``; SQLite runs the full set in
tests/unit/test_audience.py, this pins that PostgreSQL agrees.
"""

import datetime

import pytest
from app.audience import record, views
from app.audience.record import Person
from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from sqlalchemy.ext.asyncio import AsyncSession

T0 = datetime.datetime(2026, 3, 3, 10, 11)
T1 = datetime.datetime(2026, 10, 20, 14, 2)
ANNA = Person(id=51234, username="anna_n", first_name="Anna", language_code="ru")


@pytest.mark.integration
class TestAudienceOnPostgres:
    async def test_events_in_any_order_agree(self, pg_session: AsyncSession) -> None:
        renamed = Person(id=ANNA.id, username="anna", first_name="Anna", language_code="cs")
        await record.seen(pg_session, renamed, Touchpoint.MAIN_BOT, at=T1, source="vut")
        await record.seen(pg_session, ANNA, Touchpoint.MAIN_BOT, at=T0, source="matfyz")
        await pg_session.commit()

        member = await pg_session.get(AudienceMember, ANNA.id)
        assert member is not None
        assert (member.first_seen_at, member.last_seen_at) == (T0, T1)
        # The profile of the latest visit, the source of the first one recorded.
        assert (member.username, member.language_code, member.source) == ("anna", "cs", "vut")
        touch = await pg_session.get(AudienceTouch, (ANNA.id, Touchpoint.MAIN_BOT))
        assert touch is not None
        # Only a visit newer than the last one counts: an older one is history arriving late.
        assert (touch.first_at, touch.last_at, touch.count) == (T0, T1, 1)

    async def test_a_block_then_a_new_visit_reopens_the_bot(self, pg_session: AsyncSession) -> None:
        await record.blocked(pg_session, ANNA.id, Touchpoint.MAIN_BOT, at=T0)
        await record.seen(pg_session, ANNA, Touchpoint.MAIN_BOT, at=T1, started=Touchpoint.MAIN_BOT)
        await pg_session.commit()

        reach = await pg_session.get(AudienceReach, (ANNA.id, Touchpoint.MAIN_BOT))
        assert reach is not None
        assert (reach.started_at, reach.blocked_at) == (T1, None)

    async def test_the_console_queries_run_and_search_ignores_case(self, pg_session: AsyncSession) -> None:
        taras = Person(id=2, first_name="Тарас", language_code="uk")
        await record.seen(pg_session, ANNA, Touchpoint.MAIN_BOT, at=T0, started=Touchpoint.MAIN_BOT)
        await record.seen(pg_session, taras, Touchpoint.CONTACT_BOT, at=T1)
        await pg_session.commit()

        summary = await views.summary(pg_session, now=T1)
        found = await views.page(pg_session, now=T1, query="тарас")
        card = await views.person(pg_session, ANNA.id)

        assert summary["reach"] == {"reachable": 1, "never_started": 1, "blocked": 0, "opted_out": 0}
        assert summary["first_touch"]["contact_bot"] == 1
        assert [p["user_id"] for p in found["items"]] == [2]
        assert card is not None
        assert card["status"] == "reachable"

    async def test_a_payload_too_long_for_the_column_is_dropped_not_failed(self, pg_engine) -> None:
        from aiogram.types import Chat, Message, Update, User
        from app.presentation.telegram.middlewares.audience import AudienceMiddleware
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_maker = async_sessionmaker(pg_engine, expire_on_commit=False)
        person = User(id=77, is_bot=False, first_name="Long")
        message = Message(
            message_id=1,
            date=datetime.datetime.now(datetime.UTC),
            chat=Chat(id=77, type="private"),
            from_user=person,
            text="/start " + "a" * 100,
        )
        called: list[bool] = []

        async def handler(_event, _data):
            called.append(True)

        await AudienceMiddleware(session_maker, Touchpoint.MAIN_BOT)(handler, Update(update_id=1, message=message), {})

        async with session_maker() as session:
            member = await session.get(AudienceMember, 77)
        assert called == [True]
        assert member is not None
        assert member.source is None


@pytest.mark.integration
async def test_the_catalog_is_read_in_a_read_only_transaction(pg_container) -> None:
    """Against a stand-in with the catalog's column names, in a database of its own."""
    from app.audience.backfill import read_catalog
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = pg_container.get_connection_url().replace("psycopg2", "asyncpg")
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS catalog_standin"))
        await conn.execute(text("CREATE DATABASE catalog_standin"))
    await admin.dispose()

    dsn = admin_url.rsplit("/", 1)[0] + "/catalog_standin"
    catalog = create_async_engine(dsn)
    async with catalog.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE users (id serial, tg_id bigint, tg_username text, first_name text, last_name text,"
                " source text, created_at timestamptz, updated_at timestamptz, last_seen_at timestamptz,"
                " bot_started_at timestamptz, bot_can_message bool, unsubscribed_at timestamptz)"
            )
        )
        await conn.execute(
            text("INSERT INTO users (tg_id, first_name, created_at, updated_at) VALUES (5, 'X', now(), now())")
        )
    await catalog.dispose()

    [user] = await read_catalog(dsn)

    # The transaction the backfill reads in refuses a write.
    from app.audience.backfill import read_only
    from sqlalchemy.exc import DBAPIError

    catalog = create_async_engine(dsn)
    try:
        async with catalog.connect() as conn:
            await read_only(conn)
            with pytest.raises(DBAPIError, match="read-only"):
                await conn.execute(text("DELETE FROM users"))
    finally:
        await catalog.dispose()

    assert (user.tg_id, user.first_name, user.bot_started_at) == (5, "X", None)
    assert user.created_at.tzinfo is not None
