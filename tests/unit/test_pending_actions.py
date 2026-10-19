"""Destructive actions proposed from outside wait for a human press.

The point of contrast with EscalationService is expiry. An escalation that runs
out of time carries out its default action, because the bot already judged
something wrong and was only asking for a second opinion. A pending action that
runs out of time must do nothing at all: it came from a token, and silence
there has to mean no.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.enums import PendingActionStatus
from app.core.time import utc_now
from app.db.models import PendingAction
from app.moderation.pending_actions import PendingActionService

pytestmark = pytest.mark.unit

ADMIN_ID = 555
TARGET_ID = 999
CHAT_ID = -1001


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    tg_bot.edit_message_text = AsyncMock()
    return tg_bot


async def _propose(session, bot, *, action: str = "ban", expires_in_minutes: int = 30) -> PendingAction:
    service = PendingActionService(bot=bot, db=session)
    return await service.propose(
        origin="mcp",
        initiator_id=ADMIN_ID,
        action=action,
        target_user_id=TARGET_ID,
        chat_id=CHAT_ID,
        reason="proposed in a test",
        expires_in_minutes=expires_in_minutes,
    )


class TestPropose:
    async def test_nothing_is_executed_on_proposal(self, session, bot) -> None:
        executor = AsyncMock()
        service = PendingActionService(bot=bot, db=session, executor=executor)

        await service.propose(
            origin="mcp",
            initiator_id=ADMIN_ID,
            action="ban",
            target_user_id=TARGET_ID,
            chat_id=CHAT_ID,
        )

        executor.assert_not_awaited()

    async def test_proposal_reaches_the_initiating_admin(self, session, bot) -> None:
        pending = await _propose(session, bot)

        assert bot.send_message.await_args.kwargs["chat_id"] == ADMIN_ID
        assert pending.admin_chat_id == ADMIN_ID
        assert pending.admin_message_id == 42

    async def test_attribution_is_recorded(self, session, bot) -> None:
        """A ban is attributable; the token identifies a runtime, not a person."""
        pending = await _propose(session, bot)

        assert pending.origin == "mcp"
        assert pending.initiator_id == ADMIN_ID
        assert pending.status == PendingActionStatus.PENDING


class TestConfirm:
    async def test_confirm_executes_once(self, session, bot) -> None:
        executor = AsyncMock()
        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        resolved = await service.confirm(pending.id, admin_id=ADMIN_ID)

        assert resolved is not None
        assert resolved.status == PendingActionStatus.CONFIRMED
        assert resolved.resolved_by == ADMIN_ID
        executor.assert_awaited_once()

    async def test_confirmation_is_recorded_against_the_admin_who_pressed(self, session, bot) -> None:
        """The proposal came from a token; the record has to name a person."""
        from app.db.models import ModerationEvent
        from sqlalchemy import select

        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=AsyncMock())

        await service.confirm(pending.id, admin_id=ADMIN_ID)

        event = (await session.execute(select(ModerationEvent))).scalar_one()
        assert (event.action, event.source) == ("ban", "mcp")
        assert event.actor_id == ADMIN_ID
        assert (event.target_user_id, event.chat_id) == (TARGET_ID, CHAT_ID)
        assert event.detail == "proposed in a test"

    async def test_a_rejected_proposal_leaves_no_record(self, session, bot) -> None:
        from app.db.models import ModerationEvent
        from sqlalchemy import select

        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=AsyncMock())

        await service.reject(pending.id, admin_id=ADMIN_ID)

        assert (await session.execute(select(ModerationEvent))).scalars().all() == []

    async def test_second_press_does_nothing(self, session, bot) -> None:
        executor = AsyncMock()
        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        await service.confirm(pending.id, admin_id=ADMIN_ID)
        again = await service.confirm(pending.id, admin_id=ADMIN_ID)

        assert again is None
        assert executor.await_count == 1


class TestReject:
    async def test_reject_never_executes(self, session, bot) -> None:
        executor = AsyncMock()
        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        resolved = await service.reject(pending.id, admin_id=ADMIN_ID)

        assert resolved is not None
        assert resolved.status == PendingActionStatus.REJECTED
        executor.assert_not_awaited()


class TestExpiry:
    async def test_expired_action_refuses_confirmation(self, session, bot) -> None:
        executor = AsyncMock()
        pending = await _propose(session, bot, expires_in_minutes=-1)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        assert await service.confirm(pending.id, admin_id=ADMIN_ID) is None
        executor.assert_not_awaited()

        await session.refresh(pending)
        assert pending.status == PendingActionStatus.EXPIRED

    async def test_sweep_expires_without_executing(self, session, bot) -> None:
        """The invariant this table exists for."""
        executor = AsyncMock()
        pending = await _propose(session, bot, expires_in_minutes=-1)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        swept = await service.expire_stale()

        assert swept == 1
        executor.assert_not_awaited()
        await session.refresh(pending)
        assert pending.status == PendingActionStatus.EXPIRED

    async def test_sweep_leaves_live_proposals_alone(self, session, bot) -> None:
        pending = await _propose(session, bot, expires_in_minutes=30)
        service = PendingActionService(bot=bot, db=session)

        assert await service.expire_stale() == 0
        await session.refresh(pending)
        assert pending.status == PendingActionStatus.PENDING

    async def test_expiry_survives_a_restart(self, session, bot) -> None:
        """Expiry is a stored timestamp, not an in-process timer.

        EscalationService keeps its timeouts as asyncio tasks in a module dict,
        so a restart strands anything still pending. Here the sweep recovers it
        with no special path.
        """
        stale = PendingAction(
            origin="mcp",
            initiator_id=ADMIN_ID,
            action="blacklist",
            target_user_id=TARGET_ID,
            expires_at=utc_now() - datetime.timedelta(hours=6),
        )
        session.add(stale)
        await session.commit()

        assert await PendingActionService(bot=bot, db=session).expire_stale() == 1
        await session.refresh(stale)
        assert stale.status == PendingActionStatus.EXPIRED


class TestSuperAdmins:
    @pytest.mark.parametrize("action", ["blacklist", "ban"])
    async def test_removing_a_super_admin_is_refused_at_the_press(self, session, bot, monkeypatch, action) -> None:
        """A proposal older than the admin list: refused, recorded as not done."""
        from app.core.config import settings
        from app.core.exceptions import ProtectedUserError

        executor = AsyncMock()
        pending = await _propose(session, bot, action=action)
        monkeypatch.setattr(settings.admin, "super_admins", [ADMIN_ID, TARGET_ID])
        service = PendingActionService(bot=bot, db=session, executor=executor)

        with pytest.raises(ProtectedUserError):
            await service.confirm(pending.id, admin_id=ADMIN_ID)

        executor.assert_not_awaited()
        await session.refresh(pending)
        assert pending.status == PendingActionStatus.REJECTED
        assert pending.resolved_by is None, "the admin who pressed confirm did not say no"
