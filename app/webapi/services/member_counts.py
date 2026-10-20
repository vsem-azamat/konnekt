"""How many people are in a chat, as last recorded.

Read from `chat_member_snapshots` rather than asked of Telegram. This process
has no Telethon client and no session file — the account lives in the bot
container — so every count the console showed came back `None` and rendered as
a dash. The bot writes a snapshot per chat per hour; that row is the answer.

An hour stale is the trade, and it is the right one: a count that costs an API
call per chat per page load would be rate-limited long before it was fresher.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, column, select, values

from app.db.models import ChatMemberSnapshot

if TYPE_CHECKING:
    import datetime
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


async def latest_for(
    session: AsyncSession,
    chat_ids: Iterable[int],
    *,
    since: datetime.datetime | None = None,
) -> dict[int, int]:
    """The newest snapshot per chat, for as many chats as you ask about.

    One query however long the list — the chats list asks about forty-five at
    once, and forty-five round trips to answer one column would be the reason
    the page felt slow.

    Per chat asked about, the newest row through the (chat_id, captured_at)
    index, rather than the newest of every chat grouped out of the whole
    table: on 1.5M snapshots the grouping took 1.18 s and this takes under a
    millisecond. The ids go in as a CTE of VALUES, which PostgreSQL and the
    unit tests' SQLite both read.

    Chats with no snapshot are absent from the result rather than present as
    zero. "Not measured" and "empty" are different claims, and the caller has
    to be able to tell them apart. A snapshot older than `since` is no
    answer either: a count the bot last saw a week ago is history, not size.
    """
    ids = list(dict.fromkeys(chat_ids))
    if not ids:
        return {}

    asked = values(column("chat_id", BigInteger), name="asked").data([(chat_id,) for chat_id in ids]).cte()
    newest = (
        select(ChatMemberSnapshot.member_count)
        .where(ChatMemberSnapshot.chat_id == asked.c.chat_id)
        .order_by(ChatMemberSnapshot.captured_at.desc())
        .limit(1)
    )
    if since is not None:
        newest = newest.where(ChatMemberSnapshot.captured_at >= since)
    rows = (await session.execute(select(asked.c.chat_id, newest.scalar_subquery().label("member_count")))).all()
    return {row.chat_id: row.member_count for row in rows if row.member_count is not None}


async def latest(session: AsyncSession, chat_id: int) -> int | None:
    """The newest snapshot for one chat, or None if it has never been measured."""
    return (await latest_for(session, [chat_id])).get(chat_id)
