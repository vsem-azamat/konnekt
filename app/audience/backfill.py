"""Fill the audience from what was recorded before it existed. Run once after the deploy; safe to run again.

    python -m app.audience.backfill [--catalog-dsn postgresql+asyncpg://...]

Three sources, each only as good as what it kept:

- ``ads_topics``: everybody who ever wrote to the contact bot, since its start.
- the catalog's ``users``: everybody who opened the Mini App, with whether
  the main bot may write to them and whether they opted out. Read only, in a
  read-only transaction; skipped without ``--catalog-dsn``.
- the bot's ``users``, as an estimate. It holds group members as well as
  people who wrote to the bot in private, and never told the two apart. Who
  left no trace in a group (no recorded message, ad ping or moderation) is
  taken for a private contact and labelled ``ESTIMATE`` as their source; the
  bot is not marked as able to write to them until they write again. Group
  messages are kept 180 days, so someone who only wrote in a group before
  that is among the estimate.

Replayed events never pull a last-seen time back or add to a visit count,
so the order against live traffic does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.audience import record
from app.audience.record import Person
from app.core.enums import Touchpoint
from app.core.logging import get_logger
from app.db.models import AdsTopic, Message, ModerationEvent, SpamPing, User

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("audience.backfill")

ESTIMATE = "backfill:dm_estimate"


@dataclass(frozen=True)
class CatalogUser:
    """The columns of the catalog's ``users`` that say who someone is and whether we may write."""

    tg_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    source: str | None
    created_at: datetime.datetime
    last_seen_at: datetime.datetime | None
    bot_started_at: datetime.datetime | None
    bot_can_message: bool
    unsubscribed_at: datetime.datetime | None
    updated_at: datetime.datetime


async def from_contact_desk(db: AsyncSession) -> int:
    topics = list(await db.scalars(select(AdsTopic)))
    for topic in topics:
        await record.seen(
            db,
            Person(id=topic.user_id),
            Touchpoint.CONTACT_BOT,
            at=topic.created_at,
            started=Touchpoint.CONTACT_BOT,
            replay=True,
        )
    return len({topic.user_id for topic in topics})


async def from_catalog(db: AsyncSession, users: Iterable[CatalogUser]) -> int:
    count = 0
    for user in users:
        person = Person(id=user.tg_id, username=user.username, first_name=user.first_name, last_name=user.last_name)
        first = _naive(user.created_at)
        await record.seen(db, person, Touchpoint.MINI_APP, at=first, source=user.source, replay=True)
        if user.last_seen_at is not None:
            await record.seen(db, person, Touchpoint.MINI_APP, at=_naive(user.last_seen_at), replay=True)
        if user.bot_started_at is not None:
            await record.started(db, user.tg_id, Touchpoint.MAIN_BOT, at=_naive(user.bot_started_at))
        if not user.bot_can_message:
            await record.blocked(db, user.tg_id, Touchpoint.MAIN_BOT, at=_naive(user.updated_at))
        if user.unsubscribed_at is not None:
            await record.opted_out(db, user.tg_id, at=_naive(user.unsubscribed_at))
        count += 1
    return count


async def from_bot_users(db: AsyncSession) -> int:
    in_groups = select(Message.user_id).where(Message.chat_id < 0)
    pinged = select(SpamPing.user_id)
    moderated = select(ModerationEvent.target_user_id)
    users = list(
        await db.scalars(
            select(User).where(
                User.id > 0,
                User.blocked.is_(False),
                User.id.not_in(in_groups),
                User.id.not_in(pinged),
                User.id.not_in(moderated),
            )
        )
    )
    for user in users:
        person = Person(id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name)
        await record.seen(db, person, Touchpoint.MAIN_BOT, at=user.created_at, source=ESTIMATE, replay=True)
    return len(users)


async def read_catalog(dsn: str) -> list[CatalogUser]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = await conn.execute(
                text(
                    "SELECT tg_id, tg_username, first_name, last_name, source, created_at, last_seen_at,"
                    " bot_started_at, bot_can_message, unsubscribed_at, updated_at FROM users"
                )
            )
            return [CatalogUser(*row) for row in rows]
    finally:
        await engine.dispose()


def _naive(moment: datetime.datetime) -> datetime.datetime:
    """The catalog stores aware times; this database naive UTC."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(datetime.UTC).replace(tzinfo=None)


async def main(catalog_dsn: str | None) -> None:
    from app.db.session import get_session_maker

    session_maker = get_session_maker()
    async with session_maker() as db:
        desk = await from_contact_desk(db)
        catalog = await from_catalog(db, await read_catalog(catalog_dsn)) if catalog_dsn else 0
        estimated = await from_bot_users(db)
        await db.commit()
    # Counts only: never who.
    logger.info("audience_backfilled", contact_bot=desk, mini_app=catalog, main_bot_estimate=estimated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog-dsn", help="the catalog database, read only; without it the catalog is skipped")
    asyncio.run(main(parser.parse_args().catalog_dsn))
