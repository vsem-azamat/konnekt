"""Writing down who used which touchpoint, and whether a bot may still write to them.

Every write is an upsert that only moves forward: first-seen times take the
earlier value, last-seen times the later one. Live traffic and the backfill
replaying history can therefore run in any order and agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func

from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from app.db.upsert import insert_for

if TYPE_CHECKING:
    import datetime

    from aiogram.types import User
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["Person", "Touchpoint", "blocked", "seen"]


@dataclass(frozen=True)
class Person:
    """What Telegram says about somebody, and nothing more."""

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    is_bot: bool = False

    @classmethod
    def from_user(cls, user: User) -> Person:
        return cls(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code,
            is_premium=bool(user.is_premium),
            is_bot=user.is_bot,
        )

    @classmethod
    def from_web_app(cls, user: dict[str, Any]) -> Person:
        """From the ``user`` object of verified Mini App initData."""
        return cls(
            id=int(user["id"]),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            username=user.get("username"),
            language_code=user.get("language_code"),
            is_premium=bool(user.get("is_premium")),
            is_bot=bool(user.get("is_bot")),
        )


def _earlier(column: Any, value: Any) -> Any:
    return case((column <= value, column), else_=value)


def _later(column: Any, value: Any) -> Any:
    return case((column >= value, column), else_=value)


async def seen(
    db: AsyncSession,
    person: Person,
    touchpoint: Touchpoint,
    *,
    at: datetime.datetime,
    source: str | None = None,
    started: Touchpoint | None = None,
) -> None:
    """Record that `person` used `touchpoint` at `at`.

    `started` names the bot whose private chat this shows to be open, when it
    does: writing to a bot, or allowing the Mini App's bot to write.
    """
    if person.is_bot:
        return
    members = AudienceMember.__table__
    insert = insert_for(db, members).values(
        user_id=person.id,
        username=person.username,
        first_name=person.first_name,
        last_name=person.last_name,
        language_code=person.language_code,
        is_premium=person.is_premium,
        source=source,
        first_seen_at=at,
        last_seen_at=at,
    )
    newer = insert.excluded.last_seen_at >= members.c.last_seen_at
    profile = {
        # The profile as of the latest visit: an older event replayed later must not undo a rename.
        name: case((newer, insert.excluded[name]), else_=members.c[name])
        for name in ("username", "first_name", "last_name", "language_code", "is_premium")
    }
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=[members.c.user_id],
            set_={
                **profile,
                "source": func.coalesce(members.c.source, insert.excluded.source),
                "first_seen_at": _earlier(members.c.first_seen_at, insert.excluded.first_seen_at),
                "last_seen_at": _later(members.c.last_seen_at, insert.excluded.last_seen_at),
            },
        )
    )

    touches = AudienceTouch.__table__
    insert = insert_for(db, touches).values(user_id=person.id, touchpoint=touchpoint, first_at=at, last_at=at, count=1)
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=[touches.c.user_id, touches.c.touchpoint],
            set_={
                "first_at": _earlier(touches.c.first_at, insert.excluded.first_at),
                "last_at": _later(touches.c.last_at, insert.excluded.last_at),
                "count": touches.c.count + 1,
            },
        )
    )

    if started is not None:
        await _reach(db, person.id, started, started_at=at, blocked_at=None)


async def blocked(db: AsyncSession, user_id: int, bot: Touchpoint, *, at: datetime.datetime) -> None:
    """Record that `user_id` blocked `bot`: Telegram said so, or refused a send with 403."""
    await _reach(db, user_id, bot, started_at=None, blocked_at=at)


async def _reach(
    db: AsyncSession,
    user_id: int,
    bot: Touchpoint,
    *,
    started_at: datetime.datetime | None,
    blocked_at: datetime.datetime | None,
) -> None:
    reach = AudienceReach.__table__
    insert = insert_for(db, reach).values(user_id=user_id, bot=bot, started_at=started_at, blocked_at=blocked_at)
    if blocked_at is None:
        # Open again: the chat was used, so whatever block came before is over.
        changes = {
            "started_at": func.coalesce(reach.c.started_at, insert.excluded.started_at),
            "blocked_at": None,
        }
    else:
        changes = {"blocked_at": insert.excluded.blocked_at}
    await db.execute(insert.on_conflict_do_update(index_elements=[reach.c.user_id, reach.c.bot], set_=changes))
