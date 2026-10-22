"""Read-only moderation tools for the MCP control plane.

These began as the read tools of an in-process assistant that has since been
removed, and three things changed on the way out.

*Structured output.* The old tools returned prose because their only consumer
was a prompt. Here the consumer is an external runtime, so every tool returns an
explicit projection: named fields, no ORM rows, nothing that changes shape when
a column is added.

*Explicit gates.* Every tool that names a chat resolves it through
:func:`~app.mcp.deps.managed_chat_id` first, so a chat this deployment does not
manage has no id to hand on.

*Withheld fields.* A projection is also the place to decide what never leaves —
see the free-text rationale on past moderation decisions, below.

Everything here reads either our own tables or the Bot API. These tools used to
reach through a user session that could see every chat the account belonged to,
private conversations included; the gate above existed mostly to contain that.
What they can see now is bounded by what the bot was in the room for.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.mcp.deps import ToolError, clamp, managed_chat_id, moderator_bot, session_maker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

logger = get_logger("mcp.tools.read")

# Message bodies are bounded so that a 100-message page cannot dominate the
# caller's context. Telegram allows 4096 characters per message.
_MAX_TEXT = 1000


def _guarded[**P](func: Callable[P, Awaitable[dict[str, Any]]]) -> Callable[P, Awaitable[dict[str, Any]]]:
    """Turn refusals and failures into payloads the caller can read.

    ``mask_error_details`` is on, so an exception that escapes a tool reaches the
    calling runtime as "internal error" — accurate for a bug, useless for
    "that chat is not managed here". Both travel as return values instead.
    """

    # getattr because a Callable is not necessarily a function; every tool here
    # is one, but the annotation does not promise it.
    name = getattr(func, "__name__", "unknown")

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            return await func(*args, **kwargs)
        except ToolError as err:
            return err.payload()
        except Exception:
            logger.exception("mcp_read_tool_failed", tool=name)
            return {"error": "tool_failed", "tool": name}

    return wrapper


def _chat_summary(chat: Any) -> dict[str, Any]:
    """Project a Chat row, keeping its approval state visible."""
    from app.db.models import Chat

    return {
        "chat_id": chat.id,
        "title": chat.title or "",
        # A row in `chats` is not an endorsement: discovered chats are ones the
        # bot merely saw, disabled ones were switched off. Callers that treat
        # every listed chat as in-scope would act on both.
        "resource_status": chat.resource_status,
        "is_approved": chat.resource_status == Chat.STATUS_APPROVED,
        "is_forum": chat.is_forum,
        "welcome_enabled": chat.is_welcome_enabled,
        "captcha_enabled": chat.is_captcha_enabled,
        "join_mode": chat.join_mode,
        "parent_chat_id": chat.parent_chat_id,
    }


def _user_summary(user: Any) -> dict[str, Any]:
    """Project a User row."""
    return {
        "user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "blocked": user.blocked,
    }


def _escape_like(value: str) -> str:
    """Neutralise LIKE wildcards in a phrase somebody typed.

    Without this, searching for "50%" matches every message and reads as a
    chat where everybody is a spammer.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None else ""


def _message_summary(row: Any) -> dict[str, Any]:
    """Project a recorded Message row.

    `reply_to_message_id` comes out of the stored update rather than a column,
    because that is where it was kept — absent when the message replied to
    nothing, or when it predates the field being recorded.
    """
    text = row.message or ""
    reply_to = None
    info = row.message_info if isinstance(row.message_info, dict) else {}
    replied = info.get("reply_to_message")
    if isinstance(replied, dict):
        reply_to = replied.get("message_id")

    return {
        "message_id": row.message_id,
        "sender_id": row.user_id,
        "date": _iso(row.timestamp),
        "text": text[:_MAX_TEXT],
        "text_truncated": len(text) > _MAX_TEXT,
        "reply_to_message_id": reply_to,
        "flagged_spam": row.spam,
    }


def register_read_tools(mcp: FastMCP[None]) -> None:
    """Register the read-only moderation toolset on an MCP server."""

    @mcp.tool
    @_guarded
    async def list_chats(limit: int = 100) -> dict[str, Any]:
        """List the chats this deployment knows about.

        Use this to resolve a chat title into the numeric chat_id every other
        tool needs. Read resource_status before acting: only "approved" chats
        are under moderation — "discovered" ones were merely seen by the bot and
        "disabled" ones were switched off, and neither should be acted on.

        limit caps how many chats to return (1-500), newest registrations last.
        """
        from sqlalchemy import func, select

        from app.db.models import Chat

        limit = clamp(limit, 1, 500)
        async with session_maker()() as session:
            total = (await session.execute(select(func.count()).select_from(Chat))).scalar() or 0
            rows = (await session.execute(select(Chat).order_by(Chat.id).limit(limit))).scalars().all()

        return {
            "chats": [_chat_summary(row) for row in rows],
            "returned": len(rows),
            "total": total,
        }

    @mcp.tool
    @_guarded
    async def get_blacklist(limit: int = 50) -> dict[str, Any]:
        """List users on the global blacklist — blocked from every approved chat.

        limit caps how many entries to return (1-200); compare `returned` with
        `total` to see whether the list was cut short. Ask for a larger page
        only when you actually need one, rather than dumping the whole table.
        """
        from sqlalchemy import func, select

        from app.db.models import User

        limit = clamp(limit, 1, 200)
        blocked = User.blocked.is_(True)
        async with session_maker()() as session:
            total = (await session.execute(select(func.count()).select_from(User).where(blocked))).scalar() or 0
            rows = (await session.execute(select(User).where(blocked).order_by(User.id).limit(limit))).scalars().all()

        return {
            "users": [_user_summary(row) for row in rows],
            "returned": len(rows),
            "total": total,
        }

    @mcp.tool
    @_guarded
    async def get_chat_info(chat_id: int) -> dict[str, Any]:
        """Get one chat's live details — title, type, member count, description.

        chat_id is the numeric Telegram ID from list_chats; chats absent from
        that list are refused. resource_status repeats the approval state, so
        you can tell a moderated chat from a merely discovered one.
        """
        from app.db.models import Chat

        async with session_maker()() as session:
            await managed_chat_id(session, chat_id)
            row = await session.get(Chat, chat_id)

        bot = moderator_bot()
        chat = await bot.get_chat(chat_id=chat_id)
        member_count = await bot.get_chat_member_count(chat_id=chat_id)

        info: dict[str, Any] = {
            "chat_id": chat.id,
            "title": chat.title or "",
            "type": chat.type,
            "username": chat.username or "",
            "member_count": member_count,
            "description": chat.description or "",
            # Both of these used to be fetched a second time through a user
            # session. `getChat` had been carrying them all along.
            "linked_chat_id": chat.linked_chat_id,
            "resource_status": row.resource_status if row else "",
        }

        return info

    @mcp.tool
    @_guarded
    async def get_user_info(user_id: int) -> dict[str, Any]:
        """Get what this deployment has recorded about a user.

        Names and blocked status, from our own tables — so it answers about
        people the bot has seen, and `known_locally` is false for anybody else.
        There is no live profile lookup: a bot cannot read a stranger's profile,
        and the fields that used to come from a user session (bio, premium,
        photo count) were never what a moderation decision turned on.
        """
        from sqlalchemy import select

        from app.db.models import User

        async with session_maker()() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

        return {
            "user_id": user_id,
            "known_locally": user is not None,
            "username": user.username or "" if user else "",
            "first_name": user.first_name or "" if user else "",
            "last_name": user.last_name or "" if user else "",
            "blocked": user.blocked if user else False,
        }

    @mcp.tool
    @_guarded
    async def get_moderation_history(user_id: int, limit: int = 10) -> dict[str, Any]:
        """What this deployment has on record about a user's behaviour.

        Use it before proposing an action, to tell a first-time report from a
        repeat offender. Two halves: what the user did — messages seen, ones an
        admin marked as spam, hits from the ad detector — and what was done to
        them, every mute, kick, ban and blacklist entry with the admin behind it,
        however it was asked for.

        The record starts where the deployment does: actions taken before it
        existed left no row. limit caps both lists (1-50), newest first.
        """
        from sqlalchemy import func, select

        from app.db.models import Message, ModerationEvent, PendingAction, SpamPing, User

        limit = clamp(limit, 1, 50)
        async with session_maker()() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
            seen = (
                await session.execute(
                    select(func.count(), func.count(func.distinct(Message.chat_id))).where(Message.user_id == user_id)
                )
            ).one()
            flagged = (
                await session.execute(select(func.count()).where(Message.user_id == user_id, Message.spam.is_(True)))
            ).scalar() or 0
            ad_hits = (await session.execute(select(func.count()).where(SpamPing.user_id == user_id))).scalar() or 0
            proposals = (
                (
                    await session.execute(
                        select(PendingAction)
                        .where(PendingAction.target_user_id == user_id)
                        .order_by(PendingAction.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            events = (
                (
                    await session.execute(
                        select(ModerationEvent)
                        .where(ModerationEvent.target_user_id == user_id)
                        .order_by(ModerationEvent.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

        return {
            "user_id": user_id,
            "known_locally": user is not None,
            "blacklisted": bool(user and user.blocked),
            "messages_seen": seen[0],
            "chats_seen_in": seen[1],
            "messages_marked_spam": flagged,
            "ad_detector_hits": ad_hits,
            "actions_taken": [
                {
                    "action": row.action,
                    "source": row.source,
                    "actor_id": row.actor_id,
                    "chat_id": row.chat_id,
                    "detail": row.detail or "",
                    "created_at": _iso(row.created_at),
                }
                for row in events
            ],
            "proposals": [
                {
                    "action": row.action,
                    "chat_id": row.chat_id,
                    "status": row.status,
                    "reason": row.reason or "",
                    "created_at": _iso(row.created_at),
                }
                for row in proposals
            ],
        }

    @mcp.tool
    @_guarded
    async def get_chat_history(chat_id: int, limit: int = 20) -> dict[str, Any]:
        """Read recent messages from a managed chat, newest first.

        Use it to see the context around a report — what was said before and
        after. chat_id must come from list_chats; any other chat is refused.
        limit caps how many messages to return (1-100). Long message bodies are
        cut, flagged by text_truncated.

        This is what the bot recorded, not what Telegram still holds: messages
        from before it joined the chat are not here, and neither is anything it
        was not present for.
        """
        from sqlalchemy import select

        from app.db.models import Message

        async with session_maker()() as session:
            await managed_chat_id(session, chat_id)
            limit = clamp(limit, 1, 100)
            rows = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.chat_id == chat_id)
                        .order_by(Message.timestamp.desc(), Message.message_id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

        return {
            "chat_id": chat_id,
            "messages": [_message_summary(row) for row in rows],
            "returned": len(rows),
        }

    @mcp.tool
    @_guarded
    async def search_messages(chat_id: int, query: str, limit: int = 20) -> dict[str, Any]:
        """Search a managed chat's recorded messages by text, newest first.

        Use it to check whether a phrase — a spam link, a repeated insult — has
        appeared before. chat_id must come from list_chats; any other chat is
        refused. limit caps how many matches to return (1-50).

        Searches what the bot recorded, so it reaches back to when it joined the
        chat and no further. A phrase not found here is one we have no record
        of, which is a weaker claim than one that was never said.
        """
        from sqlalchemy import select

        from app.db.models import Message

        needle = query.strip()
        if not needle:
            raise ToolError("empty_query", "Give a phrase to search for.")

        async with session_maker()() as session:
            await managed_chat_id(session, chat_id)
            limit = clamp(limit, 1, 50)
            rows = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.chat_id == chat_id)
                        # ilike, so a search for a name matches how people
                        # actually type it. The escape keeps a literal % or _
                        # in the phrase from turning into a wildcard.
                        .where(Message.message.ilike(f"%{_escape_like(needle)}%", escape="\\"))
                        .order_by(Message.timestamp.desc(), Message.message_id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

        return {
            "chat_id": chat_id,
            "query": query,
            "messages": [_message_summary(row) for row in rows],
            "returned": len(rows),
        }

    @mcp.tool
    @_guarded
    async def find_users_in_chat(chat_id: int, limit: int = 50) -> dict[str, Any]:
        """List people the bot has seen writing in a managed chat, most recent first.

        Use it to resolve a display name or @username into the numeric user_id
        the moderation tools need. chat_id must come from list_chats; any other
        chat is refused. limit caps how many people to return (1-200).

        Not the membership roster: a bot cannot read one. These are the people
        who have written since the bot joined, which is both narrower — a silent
        member is absent — and wider, since somebody who has left still appears.
        Check before acting on the assumption that a listed person is present.
        """
        from sqlalchemy import func, select

        from app.db.models import Message, User

        async with session_maker()() as session:
            await managed_chat_id(session, chat_id)
            limit = clamp(limit, 1, 200)
            last_seen = (
                select(Message.user_id, func.max(Message.timestamp).label("last_seen"))
                .where(Message.chat_id == chat_id)
                .group_by(Message.user_id)
                .order_by(func.max(Message.timestamp).desc())
                .limit(limit)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(User, last_seen.c.last_seen)
                    .select_from(last_seen)
                    .join(User, User.id == last_seen.c.user_id)
                    .order_by(last_seen.c.last_seen.desc())
                )
            ).all()

        return {
            "chat_id": chat_id,
            "users": [{**_user_summary(row[0]), "last_seen": _iso(row[1])} for row in rows],
            "returned": len(rows),
        }
