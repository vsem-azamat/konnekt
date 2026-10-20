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
from app.core.enums import ModerationAction, PendingActionOrigin, PendingActionStatus
from app.core.time import utc_now
from app.db.models import Chat, PendingAction
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
    # A proposal is only ever made for a chat the bot moderates.
    if await session.get(Chat, CHAT_ID) is None:
        session.add(Chat(id=CHAT_ID, title="Moderated", resource_status=Chat.STATUS_APPROVED))
        await session.commit()
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


class TestConfirmUnderFailure:
    async def test_a_refused_action_is_not_recorded_as_done(self, session, bot) -> None:
        """Marked confirmed before the ban ran, a refusal left a record of a ban that never happened."""
        from app.db.models import ModerationEvent
        from sqlalchemy import select

        executor = AsyncMock(side_effect=RuntimeError("Bad Request: not enough rights"))
        pending = await _propose(session, bot)
        service = PendingActionService(bot=bot, db=session, executor=executor)

        with pytest.raises(RuntimeError):
            await service.confirm(pending.id, admin_id=ADMIN_ID)

        await session.refresh(pending)
        assert pending.status == PendingActionStatus.FAILED
        assert (await session.execute(select(ModerationEvent))).scalars().all() == []

    async def test_two_presses_at_once_execute_once(self, session, bot, session_maker) -> None:
        """A double tap, or two super admins: the claim must be one statement, not a read then a write."""
        import asyncio

        executor = AsyncMock()
        pending = await _propose(session, bot)

        async def press() -> object:
            async with session_maker() as own:
                return await PendingActionService(bot=bot, db=own, executor=executor).confirm(
                    pending.id, admin_id=ADMIN_ID
                )

        results = await asyncio.gather(press(), press())

        assert executor.await_count == 1
        assert sum(r is not None for r in results) == 1

    async def test_a_proposal_nobody_was_told_about_is_not_left_waiting(self, session, bot) -> None:
        """The admin never started the bot: no message, so no button anybody could press."""
        bot.send_message = AsyncMock(side_effect=RuntimeError("Forbidden: bot can't initiate conversation"))

        with pytest.raises(RuntimeError):
            await _propose(session, bot)

        from sqlalchemy import select

        rows = (await session.execute(select(PendingAction))).scalars().all()
        assert [r.status for r in rows] == [PendingActionStatus.EXPIRED]


class TestInterrupted:
    async def test_a_proposal_cut_off_mid_action_is_closed_by_the_sweep(self, session, bot) -> None:
        """The process died between the claim and the result; the row said executing forever."""
        from app.moderation.pending_actions import expire_stale

        pending = await _propose(session, bot, expires_in_minutes=-60)
        pending.status = PendingActionStatus.EXECUTING
        await session.commit()

        await expire_stale(session)

        await session.refresh(pending)
        assert pending.status == PendingActionStatus.FAILED


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


class TestTheChatAtThePress:
    @pytest.mark.parametrize(
        "status", [Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL, Chat.STATUS_DISABLED, Chat.STATUS_DISCOVERED]
    )
    async def test_a_chat_no_longer_moderated_is_refused_at_the_press(self, session, bot, status) -> None:
        """A proposal made while the chat was ours to moderate, pressed after it stopped being."""
        from app.core.exceptions import ChatNotManagedError

        executor = AsyncMock()
        pending = await _propose(session, bot)
        chat = await session.get(Chat, CHAT_ID)
        assert chat is not None
        chat.resource_status = status
        await session.commit()
        service = PendingActionService(bot=bot, db=session, executor=executor)

        with pytest.raises(ChatNotManagedError):
            await service.confirm(pending.id, admin_id=ADMIN_ID)

        executor.assert_not_awaited()
        await session.refresh(pending)
        assert pending.status == PendingActionStatus.REJECTED
        assert pending.resolved_by is None

    async def test_a_proposal_for_every_chat_names_none_and_is_not_held_up(self, session, bot) -> None:
        executor = AsyncMock()
        service = PendingActionService(bot=bot, db=session, executor=executor)
        pending = await service.propose(
            origin=PendingActionOrigin.MCP,
            initiator_id=ADMIN_ID,
            action=ModerationAction.BLACKLIST,
            target_user_id=TARGET_ID,
        )

        await service.confirm(pending.id, admin_id=ADMIN_ID)

        executor.assert_awaited_once()
