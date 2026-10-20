"""The console's ads queue, read on PostgreSQL.

The unit tests run the same statements on SQLite; this pins that PostgreSQL
agrees on the two parts that lean on the dialect: a missing author counted
as not banned, and a page boundary inside one second.
"""

import datetime

import pytest
from app.core.enums import SpamVerdict
from app.core.time import utc_now
from app.db.models import SpamPing, User
from app.webapi.services import spam_pings
from sqlalchemy.ext.asyncio import AsyncSession


def _ping(user_id: int, at: datetime.datetime) -> SpamPing:
    return SpamPing(chat_id=-1001, user_id=user_id, message_id=1, kind="link", matches=["t.me/x"], detected_at=at)


@pytest.mark.integration
class TestQueueOnPostgres:
    async def test_the_queue_skips_answered_hits_and_banned_authors(self, pg_session: AsyncSession) -> None:
        now = utc_now()
        pg_session.add_all([User(id=7, blocked=True), User(id=8)])
        answered, banned, kept, stranger = (
            _ping(8, now),
            _ping(7, now),
            _ping(8, now - datetime.timedelta(minutes=1)),
            _ping(9, now - datetime.timedelta(minutes=2)),
        )
        answered.verdict = SpamVerdict.DONE
        pg_session.add_all([answered, banned, kept, stranger])
        await pg_session.commit()

        queue = await spam_pings.read_pings(pg_session, chat_id=None, limit=10, status="unreviewed")

        assert [ping.id for ping in queue] == [kept.id, stranger.id]
        assert await spam_pings.count_unreviewed(pg_session) == 2

    async def test_pages_split_a_second_without_a_gap(self, pg_session: AsyncSession) -> None:
        same = utc_now()
        pg_session.add_all([_ping(8, same) for _ in range(3)])
        await pg_session.commit()

        first = await spam_pings.read_pings(pg_session, chat_id=None, limit=2)
        rest = await spam_pings.read_pings(pg_session, chat_id=None, limit=2, before_id=first[-1].id)

        assert len({ping.id for ping in first + rest}) == 3
