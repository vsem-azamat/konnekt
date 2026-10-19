"""Recorded messages are kept 180 days; the ones marked as spam, for good."""

from __future__ import annotations

import datetime

import pytest
from app.core.time import utc_now
from app.db.models import Message
from app.moderation.history_service import purge_old_messages
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _seed(session, message_id: int, *, days_ago: int, spam: bool = False) -> None:
    row = Message(chat_id=-100, user_id=1, message_id=message_id, message="x", message_info={}, spam=spam)
    row.timestamp = utc_now() - datetime.timedelta(days=days_ago)
    session.add(row)
    await session.commit()


async def test_old_messages_go_and_spam_and_recent_ones_stay(session) -> None:
    """A person's text is personal data; the spam filter learns from what was marked."""
    await _seed(session, 1, days_ago=200)
    await _seed(session, 2, days_ago=200, spam=True)
    await _seed(session, 3, days_ago=10)

    removed = await purge_old_messages(session, keep_days=180)

    kept = sorted((await session.scalars(select(Message.message_id))).all())
    assert (removed, kept) == (1, [2, 3])


async def test_a_large_backlog_goes_in_batches(session) -> None:
    for i in range(5):
        await _seed(session, 100 + i, days_ago=300)

    removed = await purge_old_messages(session, keep_days=180, batch=2)

    assert removed == 5
    assert (await session.scalars(select(Message.message_id))).all() == []


async def test_ad_pings_go_on_the_same_day(session) -> None:
    """A ping keeps a snippet of the text, which is the personal data the period is for."""
    from app.db.models import SpamPing

    old = SpamPing(chat_id=-100, user_id=1, message_id=1, kind="link", matches=["t.me/x"], snippet="x")
    old.detected_at = utc_now() - datetime.timedelta(days=200)
    session.add(old)
    session.add(SpamPing(chat_id=-100, user_id=1, message_id=2, kind="link", matches=["t.me/y"], snippet="y"))
    await session.commit()

    await purge_old_messages(session, keep_days=180)

    assert [p.message_id for p in (await session.scalars(select(SpamPing))).all()] == [2]
