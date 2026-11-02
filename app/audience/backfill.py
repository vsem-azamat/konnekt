"""Fill the audience from what was recorded before it existed. Run once after the deploy; safe to run again.

    python -m app.audience.backfill [--catalog-from-stdin] < catalog-dsn

The catalog's address carries its password, so it is read from stdin and
never taken as an argument, where `ps` and shell history would keep it. In
production, from the webapi container, which reaches both databases (the bot
container is on a network of its own):

    docker exec supervisor-telegram-catalog-api printenv DATABASE_URL \
      | docker exec -i supervisor-telegram-webapi python -m app.audience.backfill --catalog-from-stdin

Three sources, each only as good as what it kept:

- ``ads_topics``: everybody who ever wrote to the contact bot, since its start.
- the catalog's ``users``: everybody who opened the Mini App, and whether
  they opted out. Read only, in a read-only transaction; skipped without
  ``--catalog-from-stdin``. Its ``bot_started_at`` was set by the retired bots'
  Mini App, so it is a visit to a retired bot, not leave for the main bot to
  write. Its ``bot_can_message`` is not taken: the only time it carries is
  when the row last changed for any reason, too unreliable to order a block by.
- the bot's ``users``, as an estimate. It holds group members as well as
  people who wrote to the bot in private, and never told the two apart. Who
  left no trace in a group (no recorded message, ad ping or moderation) and
  is not in the audience already is taken for a private contact and labelled
  ``ESTIMATE`` as their source; the bot is not marked as able to write to
  them until they write again. Group messages are kept 180 days, so someone
  who only wrote in a group before that is among the estimate. Only people
  recorded before ``ESTIMATE_BEFORE``: from then on ``users`` also holds
  everybody a membership update, a join request or a button names, and an
  estimate would take them all for private contacts.

Committed every `BATCH` people, so live traffic writing the same rows never
waits on the whole run. Replayed events never pull a time back, add to a
visit count or overrule a newer block, so the order against live traffic
does not matter.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
from dataclasses import dataclass
from itertools import batched
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.audience import record
from app.audience.record import Person
from app.core.enums import Touchpoint
from app.core.logging import get_logger
from app.db.models import AdsTopic, AudienceMember, Message, ModerationEvent, SpamPing, User

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import TextIO

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

logger = get_logger("audience.backfill")

ESTIMATE = "backfill:dm_estimate"
# Shortly before the release that began recording people who never wrote
# (chat members, applicants, admins): anybody newer is not a guess to make.
ESTIMATE_BEFORE = datetime.datetime(2026, 10, 29, 16, 30)
BATCH = 200


@dataclass(frozen=True)
class CatalogUser:
    """The columns of the catalog's ``users`` that say who someone is and how they came."""

    tg_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    source: str | None
    created_at: datetime.datetime
    last_seen_at: datetime.datetime | None
    bot_started_at: datetime.datetime | None
    unsubscribed_at: datetime.datetime | None


async def from_contact_desk(session_maker: async_sessionmaker[AsyncSession]) -> int:
    async with session_maker() as db:
        topics = list(await db.execute(select(AdsTopic.user_id, AdsTopic.created_at)))
    for chunk in batched(topics, BATCH):
        async with session_maker() as db:
            for user_id, created_at in chunk:
                await record.seen(
                    db,
                    Person(id=user_id, partial=True),
                    Touchpoint.CONTACT_BOT,
                    at=created_at,
                    started=Touchpoint.CONTACT_BOT,
                    replay=True,
                )
            await db.commit()
    return len({user_id for user_id, _ in topics})


async def from_catalog(session_maker: async_sessionmaker[AsyncSession], users: Iterable[CatalogUser]) -> int:
    count = 0
    for chunk in batched(users, BATCH):
        async with session_maker() as db:
            for user in chunk:
                await _catalog_user(db, user)
            await db.commit()
        count += len(chunk)
    return count


async def _catalog_user(db: AsyncSession, user: CatalogUser) -> None:
    person = Person(
        id=user.tg_id, username=user.username, first_name=user.first_name, last_name=user.last_name, partial=True
    )
    await record.seen(db, person, Touchpoint.MINI_APP, at=_naive(user.created_at), source=user.source, replay=True)
    if user.last_seen_at is not None:
        await record.seen(db, person, Touchpoint.MINI_APP, at=_naive(user.last_seen_at), replay=True)
    if user.bot_started_at is not None:
        await record.seen(db, person, Touchpoint.MOVED_BOT, at=_naive(user.bot_started_at), replay=True)
    if user.unsubscribed_at is not None:
        await record.opted_out(db, user.tg_id, at=_naive(user.unsubscribed_at))


async def from_bot_users(session_maker: async_sessionmaker[AsyncSession]) -> int:
    async with session_maker() as db:
        users = list(
            await db.execute(
                select(User.id, User.username, User.first_name, User.last_name, User.created_at).where(
                    User.id > 0,
                    User.created_at < ESTIMATE_BEFORE,
                    User.blocked.is_(False),
                    User.id.not_in(select(Message.user_id).where(Message.chat_id < 0)),
                    User.id.not_in(select(SpamPing.user_id)),
                    User.id.not_in(select(ModerationEvent.target_user_id)),
                    # An estimate never moves what is known about somebody already here.
                    User.id.not_in(select(AudienceMember.user_id)),
                )
            )
        )
    for chunk in batched(users, BATCH):
        async with session_maker() as db:
            for user_id, username, first_name, last_name, created_at in chunk:
                person = Person(id=user_id, username=username, first_name=first_name, last_name=last_name, partial=True)
                await record.seen(db, person, Touchpoint.MAIN_BOT, at=created_at, source=ESTIMATE, replay=True)
            await db.commit()
    return len(users)


async def read_only(conn: AsyncConnection) -> None:
    """Make the transaction `conn` has begun refuse every write: the catalog is not ours to change."""
    await conn.execute(text("SET TRANSACTION READ ONLY"))


async def read_catalog(dsn: str) -> list[CatalogUser]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await read_only(conn)
            rows = await conn.execute(
                text(
                    "SELECT tg_id, tg_username, first_name, last_name, source, created_at, last_seen_at,"
                    " bot_started_at, unsubscribed_at FROM users"
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
    desk = await from_contact_desk(session_maker)
    catalog = await from_catalog(session_maker, await read_catalog(catalog_dsn)) if catalog_dsn else 0
    # Last, so whoever the other sources know is no longer an estimate.
    estimated = await from_bot_users(session_maker)
    # Counts only: never who.
    logger.info("audience_backfilled", contact_bot=desk, mini_app=catalog, main_bot_estimate=estimated)


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--catalog-from-stdin",
        action="store_true",
        help="read the catalog's database address from stdin; without it the catalog is skipped",
    )
    return parser.parse_args(argv)


def catalog_dsn(stream: TextIO) -> str:
    """The catalog's address, the first line of `stream`; never echoed, since it holds a password."""
    dsn = stream.readline().strip()
    if not dsn:
        raise SystemExit("no catalog address on stdin")
    return dsn


if __name__ == "__main__":
    args = arguments(sys.argv[1:])
    asyncio.run(main(catalog_dsn(sys.stdin) if args.catalog_from_stdin else None))
