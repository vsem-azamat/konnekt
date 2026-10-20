"""Member counts, read from what was recorded rather than asked of Telegram.

The console showed a dash for every chat, and had since the counts were added:
they were fetched through a Telethon client this process never has. The rows to
answer from were being written all along — except they were not, because the
loop writing them was started from this process too. Both halves of that are
fixed elsewhere; what is pinned here is the read.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from app.core.time import utc_now
from app.db.models import ChatMemberSnapshot
from app.webapi.services import member_counts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

FIT = -1001370017010
FS = -1001370017011
UNSEEN = -1001370017099


async def _snapshot(session_maker, chat_id: int, count: int, *, hours_ago: int) -> None:
    async with session_maker() as session:
        session.add(
            ChatMemberSnapshot(
                chat_id=chat_id,
                member_count=count,
                captured_at=utc_now() - datetime.timedelta(hours=hours_ago),
            )
        )
        await session.commit()


class TestReadingTheLatest:
    async def test_the_newest_row_wins(self, session: AsyncSession, db_session_maker) -> None:
        await _snapshot(db_session_maker, FIT, 1000, hours_ago=48)
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)

        assert await member_counts.latest(session, FIT) == 1200

    async def test_a_chat_never_measured_is_none_not_zero(self, session: AsyncSession) -> None:
        """Zero would say the room is empty. It says nothing of the sort."""
        assert await member_counts.latest(session, UNSEEN) is None

    async def test_many_chats_in_one_answer(self, session: AsyncSession, db_session_maker) -> None:
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)
        await _snapshot(db_session_maker, FS, 800, hours_ago=1)

        counts = await member_counts.latest_for(session, [FIT, FS, UNSEEN])

        assert counts == {FIT: 1200, FS: 800}

    async def test_asking_about_nothing_queries_nothing(self, session: AsyncSession) -> None:
        assert await member_counts.latest_for(session, []) == {}

    async def test_it_does_not_answer_for_chats_not_asked_about(self, session: AsyncSession, db_session_maker) -> None:
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)
        await _snapshot(db_session_maker, FS, 800, hours_ago=1)

        assert await member_counts.latest_for(session, [FIT]) == {FIT: 1200}

    async def test_a_snapshot_older_than_asked_for_is_no_answer(self, session: AsyncSession, db_session_maker) -> None:
        """An old count is not today's count: the caller says how old is too old."""
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=100)
        await _snapshot(db_session_maker, FS, 800, hours_ago=1)

        since = utc_now() - datetime.timedelta(days=3)
        assert await member_counts.latest_for(session, [FIT, FS], since=since) == {FS: 800}

    async def test_an_old_snapshot_does_not_hide_behind_a_new_one(
        self, session: AsyncSession, db_session_maker
    ) -> None:
        await _snapshot(db_session_maker, FIT, 1000, hours_ago=100)
        await _snapshot(db_session_maker, FIT, 1200, hours_ago=1)

        since = utc_now() - datetime.timedelta(days=3)
        assert await member_counts.latest_for(session, [FIT], since=since) == {FIT: 1200}
