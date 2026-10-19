"""Moderation tools that change something.

Two tiers, split by how bad the mistake is.

A mute is bounded and self-reversing, an unban restores access, a welcome
message is text — those run on the call and are recorded. A ban removes a
person, and a blacklist entry removes them from every approved chat at once; those are
proposed and wait for a super admin to press confirm in the moderator bot.

So a leaked token can queue noise into an admin's private chat, which is loud
and harmless, but it cannot remove anybody.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from app.core.enums import (
    ModerationAction,
    ModerationEventAction,
    ModerationEventSource,
    PendingActionOrigin,
)
from app.core.logging import get_logger
from app.mcp.deps import ToolError, approved_chat_id, clamp, initiator_id, moderator_bot, session_maker
from app.moderation.blacklist import is_protected
from app.moderation.mute_permissions import MUTED, UNMUTED

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = get_logger("mcp.tools.moderate")

MAX_MUTE_MINUTES = 43200


async def _record(
    action: ModerationEventAction,
    *,
    target_user_id: int,
    chat_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Record an action this plane carried out on its own.

    Runs after the action, so it never turns a completed one into a failure:
    an unattributable event is logged and dropped rather than raised. The
    missing-admin case belongs to propose time, where nothing has happened yet.
    """
    from app.moderation import audit

    try:
        actor_id = initiator_id()
    except ToolError:
        logger.warning("mcp_event_unattributed", action=action, user_id=target_user_id)
        return

    async with session_maker()() as session:
        await audit.record(
            session,
            action=action,
            source=ModerationEventSource.MCP,
            actor_id=actor_id,
            target_user_id=target_user_id,
            chat_id=chat_id,
            detail=detail,
        )


def register_moderation_tools(mcp: FastMCP[None]) -> None:
    """Register the write and confirm tiers."""

    @mcp.tool
    async def mute_user(chat_id: int, user_id: int, minutes: int = 5) -> dict[str, Any]:
        """Silence a user in one chat for a while.

        chat_id must be an approved chat — the bot does not act publicly in
        one still awaiting approval. minutes is clamped to 1..43200 (30 days);
        Telegram's own limit is 366 days, past which a mute is forever. Reversible with unmute_user,
        so this runs immediately rather than asking for confirmation.
        """
        try:
            minutes = clamp(minutes, 1, MAX_MUTE_MINUTES)
            bot = moderator_bot()
            async with session_maker()() as session:
                await approved_chat_id(session, chat_id)

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                until_date=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=minutes),
                permissions=MUTED,
                use_independent_chat_permissions=True,
            )
        except ToolError as err:
            return err.payload()

        await _record(
            ModerationEventAction.MUTE,
            target_user_id=user_id,
            chat_id=chat_id,
            detail=f"{minutes} мин.",
        )
        logger.info("mcp_mute", chat_id=chat_id, user_id=user_id, minutes=minutes)
        return {"status": "muted", "chat_id": chat_id, "user_id": user_id, "minutes": minutes}

    @mcp.tool
    async def unmute_user(chat_id: int, user_id: int) -> dict[str, Any]:
        """Restore a muted user's ability to post in one chat."""
        try:
            bot = moderator_bot()
            async with session_maker()() as session:
                await approved_chat_id(session, chat_id)

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=UNMUTED,
                use_independent_chat_permissions=True,
            )
        except ToolError as err:
            return err.payload()

        await _record(ModerationEventAction.UNMUTE, target_user_id=user_id, chat_id=chat_id)
        logger.info("mcp_unmute", chat_id=chat_id, user_id=user_id)
        return {"status": "unmuted", "chat_id": chat_id, "user_id": user_id}

    @mcp.tool
    async def unban_user(chat_id: int, user_id: int) -> dict[str, Any]:
        """Let a banned user back into one chat.

        Restores access rather than removing it, so it needs no confirmation.
        """
        try:
            bot = moderator_bot()
            async with session_maker()() as session:
                await approved_chat_id(session, chat_id)

            # Without only_if_banned Telegram's unban removes a current member.
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        except ToolError as err:
            return err.payload()

        await _record(ModerationEventAction.UNBAN, target_user_id=user_id, chat_id=chat_id)
        logger.info("mcp_unban", chat_id=chat_id, user_id=user_id)
        return {"status": "unbanned", "chat_id": chat_id, "user_id": user_id}

    @mcp.tool
    async def unblacklist_user(user_id: int) -> dict[str, Any]:
        """Remove a user from the global blacklist.

        The blacklist spans every approved chat; this lifts it in each of them.
        """
        from app.core.exceptions import UserNotFoundException
        from app.moderation.blacklist import remove_from_blacklist

        try:
            bot = moderator_bot()
            async with session_maker()() as session:
                try:
                    await remove_from_blacklist(session, bot, user_id)
                except UserNotFoundException:
                    return {"error": "unknown_user", "user_id": user_id}
        except ToolError as err:
            return err.payload()

        await _record(ModerationEventAction.UNBLACKLIST, target_user_id=user_id)
        logger.info("mcp_unblacklist", user_id=user_id)
        return {"status": "unblacklisted", "user_id": user_id}

    @mcp.tool
    async def set_welcome(chat_id: int, message: str = "", enabled: bool = True) -> dict[str, Any]:
        """Set a chat's welcome text and whether it is enabled.

        The greeting is posted when someone joins and removed again after the
        chat's configured lifetime. Passing an empty message leaves the existing
        text alone and only changes the toggle.
        """
        from sqlalchemy import select

        from app.db.models import Chat

        try:
            async with session_maker()() as session:
                await approved_chat_id(session, chat_id)
                chat = await session.scalar(select(Chat).where(Chat.id == chat_id))
                if chat is None:  # pragma: no cover - approved_chat_id already refused
                    return {"error": "unknown_chat"}
                if message:
                    chat.welcome_message = message
                chat.is_welcome_enabled = enabled
                await session.commit()
        except ToolError as err:
            return err.payload()

        logger.info("mcp_set_welcome", chat_id=chat_id, enabled=enabled)
        return {"status": "updated", "chat_id": chat_id, "enabled": enabled}

    # ── confirm tier ──────────────────────────────────────────────────────

    @mcp.tool
    async def propose_ban(chat_id: int, user_id: int, reason: str = "") -> dict[str, Any]:
        """Ask a super admin to ban a user from one chat.

        Nothing happens until a human presses confirm in the moderator bot, and
        the request expires on its own if nobody does. Returns the pending id so
        you can tell the operator what is waiting for them.
        """
        return await _propose(ModerationAction.BAN, chat_id=chat_id, user_id=user_id, reason=reason)

    @mcp.tool
    async def propose_blacklist(user_id: int, reason: str = "") -> dict[str, Any]:
        """Ask a super admin to blacklist a user across every approved chat.

        The widest action available here, and the one least worth getting wrong,
        so it waits for a human press and expires unanswered.
        """
        return await _propose(ModerationAction.BLACKLIST, chat_id=None, user_id=user_id, reason=reason)


async def _propose(action: ModerationAction, *, chat_id: int | None, user_id: int, reason: str) -> dict[str, Any]:
    from app.moderation.pending_actions import PendingActionService

    try:
        if action is ModerationAction.BLACKLIST and is_protected(user_id):
            raise ToolError("protected_user", f"User {user_id} is a super admin and cannot be blacklisted.")
        admin_id = initiator_id()
        bot = moderator_bot()
        async with session_maker()() as session:
            if chat_id is not None:
                await approved_chat_id(session, chat_id)
            pending = await PendingActionService(bot=bot, db=session).propose(
                origin=PendingActionOrigin.MCP,
                initiator_id=admin_id,
                action=action,
                target_user_id=user_id,
                chat_id=chat_id,
                reason=reason or None,
            )
            pending_id = pending.id
            expires_at = pending.expires_at.isoformat()
    except ToolError as err:
        return err.payload()

    logger.info("mcp_proposed", action=action, pending_id=pending_id, user_id=user_id)
    return {
        "status": "awaiting_confirmation",
        "pending_id": pending_id,
        "action": action,
        "user_id": user_id,
        "expires_at": expires_at,
    }
