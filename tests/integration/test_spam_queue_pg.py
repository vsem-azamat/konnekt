"""The console's ads queue, read on PostgreSQL.

The unit tests run the same statements on SQLite; this pins that PostgreSQL
agrees on the parts that lean on the dialect: the conditional answer, the
row-value cursor, and the partial index and check the migration declares.
"""

import datetime

import pytest
from app.core.enums import SpamVerdict
from app.core.time import utc_now
from app.db.models import SpamPing
from app.webapi.services import spam_pings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _ping(at: datetime.datetime) -> SpamPing:
    return SpamPing(chat_id=-1001, user_id=8, message_id=1, kind="link", matches=["t.me/x"], detected_at=at)


@pytest.mark.integration
class TestQueueOnPostgres:
    async def test_an_answer_stands_against_a_second_one(self, pg_session: AsyncSession) -> None:
        ping = _ping(utc_now())
        pg_session.add(ping)
        await pg_session.commit()

        await spam_pings.review_ping(pg_session, ping.id, SpamVerdict.NOT_AD, admin_id=1)
        with pytest.raises(spam_pings.AlreadyAnsweredError):
            await spam_pings.review_ping(pg_session, ping.id, SpamVerdict.DONE, admin_id=2)

        assert await spam_pings.count_unreviewed(pg_session) == 0

    async def test_pages_split_a_second_without_a_gap(self, pg_session: AsyncSession) -> None:
        same = utc_now()
        pg_session.add_all([_ping(same) for _ in range(3)])
        await pg_session.commit()

        first = await spam_pings.read_pings(pg_session, chat_id=None, limit=2)
        last = first[-1]
        rest = await spam_pings.read_pings(pg_session, chat_id=None, limit=2, before=(last.detected_at, last.id))

        assert len({ping.id for ping in first + rest}) == 3

    async def test_a_verdict_outside_the_three_is_refused_by_the_database(self, pg_session: AsyncSession) -> None:
        ping = _ping(utc_now())
        ping.verdict = "maybe"
        pg_session.add(ping)
        with pytest.raises(IntegrityError):
            await pg_session.commit()
