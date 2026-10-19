"""Destructive actions proposed from outside, held until an admin presses.

Expiry is a stored timestamp, checked when the action is read and swept in the
background — not an ``asyncio`` task in a module-level dict. A timer exists only
in the process that created it, so a proposal raised in one process and
confirmed in another would never expire; a timestamp survives restarts and
process boundaries alike. The moderation agent's escalations worked the other
way and were lost on every restart.

Expiry also does nothing. That is the other half of the difference: an
escalation timed out *into* its default action, which suits a bot that has
already judged something wrong and wants a second opinion. A proposal arrives
from outside, and silence about one has to mean no.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, Any, Protocol

from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, update

from app.core.enums import (
    ModerationAction,
    ModerationEventAction,
    ModerationEventSource,
    PendingActionOrigin,
    PendingActionStatus,
)
from app.core.exceptions import ProtectedUserError
from app.core.logging import get_logger
from app.core.text import escape_html
from app.core.time import utc_now
from app.db.models import PendingAction
from app.moderation import audit
from app.moderation.blacklist import is_protected

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# The press's contract, owned by the feature that sends the buttons; the
# bot's handler reads it.
class PendingActionDecision(CallbackData, prefix="pact"):
    """Confirm or drop a destructive action proposed from outside.

    Typed rather than hand-built from an f-string, so aiogram validates the
    64-byte limit instead of leaving it to arithmetic.
    """

    pending_id: int
    confirm: int


logger = get_logger("moderation.pending_actions")

DEFAULT_EXPIRY_MINUTES = 60

_ACTION_LABELS = {
    ModerationAction.BAN: "забанить",
    ModerationAction.BLACKLIST: "занести в чёрный список",
}


SWEEP_INTERVAL_SECONDS = 300


async def expire_stale(db: AsyncSession) -> int:
    """Mark everything past its deadline as expired. Executes nothing.

    A free function because expiry needs no bot: nothing is sent, nothing is
    carried out. The sweep can therefore run without a Telegram session at all.
    """
    now = utc_now()
    # Claimed and then cut off: the process died between the press and the
    # result. Nobody knows whether it ran, so it is closed as failed rather
    # than left saying "executing" with live buttons that do nothing.
    interrupted = await db.execute(
        update(PendingAction)
        .where(
            PendingAction.status == PendingActionStatus.EXECUTING,
            PendingAction.expires_at <= now - datetime.timedelta(minutes=10),
        )
        .values(status=PendingActionStatus.FAILED, resolved_at=now)
    )
    if interrupted.rowcount:  # ty: ignore[unresolved-attribute]
        await db.commit()
        logger.warning("pending_actions_interrupted", count=interrupted.rowcount)  # ty: ignore[unresolved-attribute]
    stale = (
        (
            await db.execute(
                select(PendingAction.id).where(
                    PendingAction.status == PendingActionStatus.PENDING,
                    PendingAction.expires_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    if not stale:
        return 0

    await db.execute(
        update(PendingAction)
        .where(PendingAction.id.in_(stale))
        .values(status=PendingActionStatus.EXPIRED, resolved_at=now)
    )
    await db.commit()
    logger.info("pending_actions_expired", count=len(stale))
    return len(stale)


class ActionExecutor(Protocol):
    """Carries out a confirmed action. Injected so tests need no live bot."""

    async def __call__(self, pending: PendingAction, bot: Bot, db: AsyncSession) -> None: ...


async def _execute(pending: PendingAction, bot: Bot, db: AsyncSession) -> None:
    """Carry out a confirmed proposal."""
    from app.moderation.actions import apply, parse

    params = dict(pending.params or {})
    await apply(
        parse(pending.action),
        bot=bot,
        db=db,
        user_id=pending.target_user_id,
        chat_id=pending.chat_id,
        revoke_messages=bool(params.get("revoke_messages", False)),
    )


class PendingActionService:
    """Propose, confirm, reject and expire actions awaiting a human press."""

    def __init__(
        self,
        bot: Bot,
        db: AsyncSession,
        executor: ActionExecutor | None = None,
    ) -> None:
        self.bot = bot
        self.db = db
        self._execute = executor or _execute

    async def propose(
        self,
        *,
        origin: PendingActionOrigin,
        initiator_id: int,
        action: ModerationAction,
        target_user_id: int,
        chat_id: int | None = None,
        params: dict[str, Any] | None = None,
        reason: str | None = None,
        expires_in_minutes: int = DEFAULT_EXPIRY_MINUTES,
    ) -> PendingAction:
        """Record the proposal and put it in front of the initiating admin."""
        pending = PendingAction(
            origin=origin,
            initiator_id=initiator_id,
            action=action,
            target_user_id=target_user_id,
            expires_at=utc_now() + datetime.timedelta(minutes=expires_in_minutes),
            chat_id=chat_id,
            params=params,
            reason=reason,
        )
        self.db.add(pending)
        await self.db.commit()
        await self.db.refresh(pending)

        try:
            message = await self.bot.send_message(
                chat_id=initiator_id,
                text=self._render(pending),
                reply_markup=self._keyboard(pending.id),
            )
        except Exception:
            # Nobody was shown a button, so nobody can say yes; left pending it
            # would only wait for the sweep while the caller is told nothing.
            await self._mark(pending, PendingActionStatus.EXPIRED, admin_id=None)
            logger.warning("pending_action_not_delivered", pending_id=pending.id, initiator_id=initiator_id)
            raise
        pending.admin_chat_id = initiator_id
        pending.admin_message_id = message.message_id
        await self.db.commit()

        logger.info(
            "pending_action_proposed",
            pending_id=pending.id,
            origin=origin,
            action=action,
            initiator_id=initiator_id,
            target_user_id=target_user_id,
        )
        return pending

    async def confirm(self, pending_id: int, admin_id: int) -> PendingAction | None:
        """Execute the action. Returns None if it is gone, taken or expired."""
        pending = await self._claim(pending_id)
        if pending is None:
            return None

        if pending.expires_at <= utc_now():
            await self._mark(pending, PendingActionStatus.EXPIRED, admin_id=None)
            logger.info("pending_action_expired_on_press", pending_id=pending_id)
            return None

        # A proposal can outlive a change to the admin list; refused here before
        # it is marked done, so the record does not say it happened.
        if is_protected(pending.target_user_id):
            # Nobody said no: the rule did. The record names no admin, as for
            # an expired proposal.
            await self._mark(pending, PendingActionStatus.REJECTED, admin_id=None)
            logger.warning("pending_action_refused_protected", pending_id=pending_id, admin_id=admin_id)
            raise ProtectedUserError(pending.target_user_id)

        try:
            await self._execute(pending, self.bot, self.db)
        except Exception:
            # Written down after it succeeds, never before: a refusal is a
            # failure on record, not a ban that never happened.
            await self.db.rollback()
            await self._mark(pending, PendingActionStatus.FAILED, admin_id=admin_id)
            logger.warning("pending_action_failed", pending_id=pending_id, admin_id=admin_id, exc_info=True)
            raise
        await self._mark(pending, PendingActionStatus.CONFIRMED, admin_id=admin_id)
        # The proposal came from outside; the person who pressed confirm is the
        # one the record names, which is the whole point of the confirm tier.
        await audit.record(
            self.db,
            action=ModerationEventAction(pending.action),
            source=ModerationEventSource(pending.origin),
            actor_id=admin_id,
            target_user_id=pending.target_user_id,
            chat_id=pending.chat_id,
            detail=pending.reason,
        )
        logger.info("pending_action_confirmed", pending_id=pending_id, admin_id=admin_id, action=pending.action)
        return pending

    async def reject(self, pending_id: int, admin_id: int) -> PendingAction | None:
        """Drop the proposal without executing anything."""
        pending = await self._claim(pending_id)
        if pending is None:
            return None

        await self._mark(pending, PendingActionStatus.REJECTED, admin_id=admin_id)
        logger.info("pending_action_rejected", pending_id=pending_id, admin_id=admin_id)
        return pending

    async def expire_stale(self) -> int:
        """Convenience wrapper for callers that already hold a service."""
        return await expire_stale(self.db)

    async def _claim(self, pending_id: int) -> PendingAction | None:
        """Take the proposal out of pending, or find it already taken.

        One UPDATE, so of two presses at once exactly one wins: a read and a
        write let both through, and the ban ran twice.
        """
        claimed = await self.db.execute(
            update(PendingAction)
            .where(PendingAction.id == pending_id, PendingAction.status == PendingActionStatus.PENDING)
            .values(status=PendingActionStatus.EXECUTING)
        )
        await self.db.commit()
        if claimed.rowcount != 1:  # ty: ignore[unresolved-attribute]
            return None
        return await self.db.get(PendingAction, pending_id, populate_existing=True)

    async def _mark(self, pending: PendingAction, status: PendingActionStatus, *, admin_id: int | None) -> None:
        pending.status = status
        pending.resolved_by = admin_id
        pending.resolved_at = utc_now()
        await self.db.commit()

    def _render(self, pending: PendingAction) -> str:
        from app.moderation.actions import parse

        label = _ACTION_LABELS[parse(pending.action)]
        lines = [
            f"Запрошено действие: <b>{escape_html(label)}</b>",
            f"Пользователь: <code>{pending.target_user_id}</code>",
        ]
        if pending.chat_id is not None:
            lines.append(f"Чат: <code>{pending.chat_id}</code>")
        if pending.reason:
            lines.append(f"Причина: {escape_html(pending.reason)}")
        lines.append(f"Источник: <code>{escape_html(pending.origin)}</code>")
        lines.append("\nБез подтверждения ничего не произойдёт.")
        return "\n".join(lines)

    @staticmethod
    def _keyboard(pending_id: int):
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Подтвердить", callback_data=PendingActionDecision(pending_id=pending_id, confirm=1))
        builder.button(text="✖️ Отклонить", callback_data=PendingActionDecision(pending_id=pending_id, confirm=0))
        builder.adjust(2)
        return builder.as_markup()


async def run_expiry_sweep(
    session_maker: async_sessionmaker[AsyncSession],
    interval_seconds: int = SWEEP_INTERVAL_SECONDS,
) -> None:
    """Periodically retire proposals nobody answered.

    Correctness does not depend on this — ``confirm`` refuses anything past its
    deadline on its own. The sweep is here so the stored status stops claiming
    a proposal is still awaiting an answer when it is not, including the ones
    left behind by a restart.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with session_maker() as session:
                await expire_stale(session)
        except asyncio.CancelledError:
            logger.info("pending_action_sweep_cancelled")
            raise
        except Exception:
            logger.exception("pending_action_sweep_failed")
