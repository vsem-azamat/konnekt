"""The record of what moderators did.

Two things worth pinning: a row lands with the actor on it, and a failure to
write one never becomes the caller's problem — by the time the record is
written the ban has already happened.
"""

from typing import TYPE_CHECKING, cast

import pytest
from app.core.enums import (
    ModerationEventAction,
    ModerationEventSource,
)
from app.db.models import ModerationEvent
from app.moderation import audit
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit


async def test_a_record_names_the_actor_and_the_target(session) -> None:
    await audit.record(
        session,
        action=ModerationEventAction.BAN,
        source=ModerationEventSource.COMMAND,
        actor_id=42,
        target_user_id=777,
        chat_id=-100123,
        detail="ads",
    )

    event = (await session.execute(select(ModerationEvent))).scalar_one()
    assert (event.action, event.source) == ("ban", "command")
    assert (event.actor_id, event.target_user_id, event.chat_id) == (42, 777, -100123)
    assert event.detail == "ads"
    assert event.created_at is not None


async def test_the_blacklist_is_recorded_without_a_chat(session) -> None:
    """It holds everywhere, so naming one chat would be a smaller claim than the truth."""
    await audit.record(
        session,
        action=ModerationEventAction.BLACKLIST,
        source=ModerationEventSource.MCP,
        actor_id=42,
        target_user_id=777,
    )

    event = (await session.execute(select(ModerationEvent))).scalar_one()
    assert event.chat_id is None


async def test_a_failed_write_does_not_reach_the_caller() -> None:
    """The action already happened; an error here would report the opposite."""

    class BrokenSession:
        def __init__(self) -> None:
            self.rolled_back = False

        def add(self, _obj) -> None:
            raise RuntimeError("database is gone")

        async def commit(self) -> None:  # pragma: no cover - never reached
            raise AssertionError("commit should not be attempted")

        async def rollback(self) -> None:
            self.rolled_back = True

    broken = BrokenSession()

    await audit.record(
        cast("AsyncSession", broken),
        action=ModerationEventAction.KICK,
        source=ModerationEventSource.COMMAND,
        actor_id=42,
        target_user_id=777,
    )

    assert broken.rolled_back is True
