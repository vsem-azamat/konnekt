"""The newest member count per chat, read on PostgreSQL.

The query walks the (chat_id, captured_at) index once per chat asked about
instead of grouping the whole table: on a synthetic table of 1.5M snapshots
over 300 chats, 1.18 s for the grouping against 0.55 ms for this. SQLite runs
the same statement in the unit tests; this pins that PostgreSQL agrees.
"""

import datetime

import pytest
from app.core.time import utc_now
from app.db.models import ChatMemberSnapshot
from app.webapi.services import member_counts
from sqlalchemy.ext.asyncio import AsyncSession

FIT = -1001370017010
FS = -1001370017011
UNSEEN = -1001370017099


@pytest.mark.integration
class TestLatestOnPostgres:
    async def test_the_newest_row_per_chat_and_only_for_chats_asked_about(self, pg_session: AsyncSession) -> None:
        now = utc_now()
        pg_session.add_all(
            [
                ChatMemberSnapshot(chat_id=FIT, member_count=1000, captured_at=now - datetime.timedelta(hours=48)),
                ChatMemberSnapshot(chat_id=FIT, member_count=1200, captured_at=now - datetime.timedelta(hours=1)),
                ChatMemberSnapshot(chat_id=FS, member_count=800, captured_at=now - datetime.timedelta(hours=1)),
            ]
        )
        await pg_session.commit()

        assert await member_counts.latest_for(pg_session, [FIT, UNSEEN]) == {FIT: 1200}
        assert await member_counts.latest_for(pg_session, [FIT, FS, UNSEEN]) == {FIT: 1200, FS: 800}

    async def test_too_old_is_no_answer(self, pg_session: AsyncSession) -> None:
        now = utc_now()
        pg_session.add_all(
            [
                ChatMemberSnapshot(chat_id=FIT, member_count=1200, captured_at=now - datetime.timedelta(days=4)),
                ChatMemberSnapshot(chat_id=FS, member_count=800, captured_at=now - datetime.timedelta(hours=1)),
            ]
        )
        await pg_session.commit()

        since = now - datetime.timedelta(days=3)
        assert await member_counts.latest_for(pg_session, [FIT, FS], since=since) == {FS: 800}
