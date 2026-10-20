"""Writing down who used which touchpoint, and whether a bot may still write to them.

Every write is an upsert that only moves forward: first-seen times take the
earlier value, last-seen times the later one, and whether a bot may write is
decided by the latest event about it. Live traffic and the backfill
replaying history can therefore run in any order and agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, null, update

from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceReach, AudienceTouch
from app.db.upsert import insert_for

if TYPE_CHECKING:
    import datetime

    from aiogram.types import User
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["Person", "Touchpoint", "blocked", "opted_out", "seen", "started"]

# A start or startapp payload that can be stored as where somebody came from:
# what our own links carry. Anything else is somebody typing, and is not kept.
SOURCE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_PROFILE = ("username", "first_name", "last_name", "language_code", "is_premium")


@dataclass(frozen=True)
class Person:
    """What Telegram says about somebody, and nothing more."""

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool | None = None
    is_bot: bool = False
    # From a source that keeps only part of the profile, as the backfill's do:
    # what it lacks is unknown, not removed, and never overwrites a live visit.
    # Telegram's own User is the whole profile: a missing last name is no last name.
    partial: bool = False

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
    replay: bool = False,
) -> None:
    """Record that `person` used `touchpoint` at `at`.

    `started` names the bot whose private chat this shows to be open, when it
    does: writing to a bot, or allowing the Mini App's bot to write. A visit
    counts only when it is newer than the last one recorded, so the same
    event delivered twice counts once; a `replay` of history, as the backfill
    does, never counts.
    """
    if person.is_bot:
        return
    members = AudienceMember.__table__
    profile_now = {name: getattr(person, name) for name in _PROFILE}
    # A partial source only adds; is_premium cannot be null.
    known = {
        name: value
        for name, value in profile_now.items()
        if value is not None or (not person.partial and name != "is_premium")
    }
    insert = insert_for(db, members).values(
        user_id=person.id,
        **known,
        source=source,
        first_seen_at=at,
        last_seen_at=at,
    )
    newer = insert.excluded.last_seen_at >= members.c.last_seen_at
    profile = {
        # The profile as of the latest visit: an older event replayed later must not undo a rename.
        name: case((newer, insert.excluded[name]), else_=members.c[name])
        for name in known
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
    visit = 0 if replay else case((touches.c.last_at < insert.excluded.last_at, 1), else_=0)
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=[touches.c.user_id, touches.c.touchpoint],
            set_={
                "first_at": _earlier(touches.c.first_at, insert.excluded.first_at),
                "last_at": _later(touches.c.last_at, insert.excluded.last_at),
                "count": touches.c.count + visit,
            },
        )
    )

    if started is not None:
        await _reach(db, person.id, started, at=at, open_=True)


async def started(db: AsyncSession, user_id: int, bot: Touchpoint, *, at: datetime.datetime) -> None:
    """Record that `bot` may write to `user_id` from `at`, without it being a visit: an unblock."""
    await _member(db, user_id, at)
    await _reach(db, user_id, bot, at=at, open_=True)


async def blocked(db: AsyncSession, user_id: int, bot: Touchpoint, *, at: datetime.datetime) -> None:
    """Record that `user_id` blocked `bot`: Telegram said so, or refused a send with 403.

    Somebody can block a bot before this table first saw them; they used it,
    so they are audience from then.
    """
    await _member(db, user_id, at)
    await _reach(db, user_id, bot, at=at, open_=False)


async def _member(db: AsyncSession, user_id: int, at: datetime.datetime) -> None:
    members = AudienceMember.__table__
    insert = insert_for(db, members).values(user_id=user_id, first_seen_at=at, last_seen_at=at)
    await db.execute(insert.on_conflict_do_nothing(index_elements=[members.c.user_id]))


async def _reach(db: AsyncSession, user_id: int, bot: Touchpoint, *, at: datetime.datetime, open_: bool) -> None:
    reach = AudienceReach.__table__
    insert = insert_for(db, reach).values(
        user_id=user_id,
        bot=bot,
        started_at=at if open_ else None,
        blocked_at=None if open_ else at,
        known_at=at,
    )
    # Only an event at least as new as the one that set the state changes it.
    newer = reach.c.known_at <= at
    changes: dict[str, Any] = {
        "blocked_at": case((newer, null() if open_ else at), else_=reach.c.blocked_at),
        "known_at": _later(reach.c.known_at, at),
    }
    if open_:
        changes["started_at"] = _earlier(reach.c.started_at, at)
    await db.execute(insert.on_conflict_do_update(index_elements=[reach.c.user_id, reach.c.bot], set_=changes))


async def opted_out(db: AsyncSession, user_id: int, *, at: datetime.datetime) -> None:
    """Record that `user_id` asked not to hear from us; only they can take it back."""
    await db.execute(
        update(AudienceMember)
        .where(AudienceMember.user_id == user_id, AudienceMember.opted_out_at.is_(None))
        .values(opted_out_at=at)
    )
