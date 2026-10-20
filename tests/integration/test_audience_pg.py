"""The audience upserts, on PostgreSQL.

They are written once for both dialects (`app.db.upsert`), and the order
rules live in CASE expressions over ``excluded``; SQLite runs the full set in
tests/unit/test_audience.py, this pins that PostgreSQL agrees.
"""

import datetime

import pytest
from app.audience import record
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
        assert (touch.first_at, touch.last_at, touch.count) == (T0, T1, 2)

    async def test_a_block_then_a_new_visit_reopens_the_bot(self, pg_session: AsyncSession) -> None:
        await record.blocked(pg_session, ANNA.id, Touchpoint.MAIN_BOT, at=T0)
        await record.seen(pg_session, ANNA, Touchpoint.MAIN_BOT, at=T1, started=Touchpoint.MAIN_BOT)
        await pg_session.commit()

        reach = await pg_session.get(AudienceReach, (ANNA.id, Touchpoint.MAIN_BOT))
        assert reach is not None
        assert (reach.started_at, reach.blocked_at) == (T1, None)
