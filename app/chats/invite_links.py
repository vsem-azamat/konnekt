"""The invite link the bot keeps for a listed chat that has no username.

The catalogue serves `chats.public_link`. For a public chat that is
`t.me/<username>`; for a private one it is a link the bot made itself, kept
here. Which chats are listed is decided elsewhere and by people: this module
never publishes a chat, it only keeps the link of one already listed working.

Telegram sends nothing when an administrator revokes a link, so the bot finds
out by using it. `editChatInviteLink` succeeds only for a link the bot itself
created and that is still live, which makes it one call that both proves
ownership and detects revocation. A link made by hand with the bot's token is
adopted by the same call, in place, rather than recreated.

A dead link is replaced; a bot that cannot replace it (no invite right, removed
from the chat) says so once, loudly, and keeps serving the old link, which is
no worse than having nothing. Transient failures change nothing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import case, select, update

from app.chats.metadata import ask
from app.chats.metrics import INVITE_LINK_EVENTS, INVITE_LINK_PROBLEMS
from app.core.logging import get_logger
from app.db.models import Chat

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import ChatInviteLink
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.invite_links")

# The name Telegram shows to an administrator looking at the chat's links, and
# the one the links made by hand already carry.
LINK_NAME = "Konnekt catalog"
# Only chats we run. `observed` ones are another bot's to act in (docs/invariants.md)
# and `external` ones are somebody else's room the bot may not even be in.
MANAGED_STATUSES = (Chat.STATUS_APPROVED,)
# More dead links than this in one sweep is Telegram or this code misbehaving,
# not administrators revoking: stop rather than mint links across the catalogue.
MAX_REPLACEMENTS_PER_SWEEP = 5
# Set when that happens and kept until the process restarts: a pause of one
# sweep only re-links the next few chats every quarter of an hour.
_halted = False
SYNC_INTERVAL_SECONDS = 900
# One edit and one lookup per chat; a second apart keeps a tick clear of flood control.
PAUSE_BETWEEN_CHATS_SECONDS = 1.0

# The chats whose link the bot cannot mend, and why: the one memory that keeps
# a standing problem from being reported again every tick. Per process; a
# restart reports what is still broken once more, which is the right reminder.
_problems: dict[int, str] = {}


def forget_problems() -> None:
    global _halted
    _problems.clear()
    _halted = False


def is_invite_link(link: str) -> bool:
    """A `t.me/+hash` or `joinchat` link, as opposed to a username."""
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return tail.startswith("+") or "joinchat" in link


def _usable(link: ChatInviteLink) -> bool:
    """Whether a link Telegram just edited is one a stranger can still join by.

    Only revocation is read from the answer: an edit replaces the whole link, so
    an expiry or member limit somebody had set is cleared by it, not reported.
    """
    return not link.is_revoked


def _transient(err: Exception) -> bool:
    return isinstance(err, TelegramRetryAfter | TelegramNetworkError | TelegramServerError | ClientDecodeError)


def _problem_of(err: Exception) -> str:
    """Why the bot cannot make a link: a right it lacks, or a chat it is no longer in."""
    text = str(err).lower()
    if "not enough rights" in text or "admin_required" in text or "admin required" in text:
        return "no_invite_right"
    if isinstance(err, TelegramForbiddenError) or "chat not found" in text or "kicked" in text:
        return "not_in_chat"
    return "create_failed"


def _report(chat: Chat, problem: str) -> str:
    """Say a link cannot be mended, once per problem; return it as the outcome."""
    if _problems.get(chat.id) != problem:
        _problems[chat.id] = problem
        # An error reaches the report chat; the standing state does not repeat it.
        # The chat is in the event's name because the report chat gets only the
        # name, and alerts are throttled per name: a shared one would hide the
        # second broken chat for half an hour.
        logger.error(f"invite_link_unrecoverable chat={chat.id}", chat_id=chat.id, problem=problem)
    else:
        logger.info("invite_link_still_broken", chat_id=chat.id, problem=problem)
    return problem


def _settled(chat: Chat) -> None:
    if _problems.pop(chat.id, None) is not None:
        logger.info("invite_link_recovered", chat_id=chat.id)


async def _retire_by_id(bot: Bot, chat_id: int, link: str) -> None:
    """Revoke a link of ours that nothing serves any more; never at the cost of the caller."""
    try:
        await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=link)
    except (TelegramAPIError, ClientDecodeError) as err:
        logger.info("invite_link_not_retired", chat_id=chat_id, error=str(err), error_type=type(err).__name__)


async def _retire(bot: Bot, chat: Chat, link: str) -> None:
    await _retire_by_id(bot, chat.id, link)


async def ensure_link(bot: Bot, chat: Chat) -> str:
    """Make `chat.public_link` a link that works; returns what was done.

    The caller commits. Outcomes: `kept`, `created`, `replaced`, `username`,
    `transient` (nothing known, nothing changed), or a problem the bot cannot
    mend (`no_invite_right`, `not_in_chat`, `create_failed`).
    """
    try:
        info = await ask(lambda: bot.get_chat(chat.id))
    except (TelegramAPIError, ClientDecodeError) as err:
        if _transient(err):
            return "transient"
        return _report(chat, _problem_of(err))

    current = chat.public_link
    if info.username:
        target = f"https://t.me/{info.username}"
        if current is not None and current.casefold() == target.casefold():
            _settled(chat)
            return "kept"
        chat.public_link = target
        if current is not None and is_invite_link(current):
            if chat.join_mode == Chat.JOIN_OPEN:
                chat.join_mode = Chat.JOIN_ADMINS
            await _retire(bot, chat, current)
        _settled(chat)
        return "username"

    # Only a chat that lets everyone in, and is ours to decide for, may hand
    # out a link that skips the request: anywhere else it would skip the check.
    lets_everyone_in = chat.resource_status == Chat.STATUS_APPROVED and chat.join_mode == Chat.JOIN_OPEN
    wants_request = not lets_everyone_in or bool(info.join_by_request)

    had_link = current is not None and is_invite_link(current)
    stale: str | None = None
    if had_link:
        assert current is not None
        try:
            edited = await ask(
                lambda: bot.edit_chat_invite_link(
                    chat_id=chat.id, invite_link=current, name=LINK_NAME, creates_join_request=wants_request
                )
            )
        except (TelegramAPIError, ClientDecodeError) as err:
            if _transient(err):
                return "transient"
            if isinstance(err, TelegramBadRequest) and "not modified" in str(err).lower():
                _settled(chat)
                return "kept"
            # Revoked, expired, never ours, or the right is gone: whichever it
            # is, making a fresh link tells the difference.
        else:
            if _usable(edited):
                _settled(chat)
                return "kept"
            # Revoked only once its replacement exists: a failed create must
            # leave the catalogue a link rather than none.
            stale = current

    try:
        made = await ask(
            lambda: bot.create_chat_invite_link(chat_id=chat.id, name=LINK_NAME, creates_join_request=wants_request)
        )
    except (TelegramAPIError, ClientDecodeError) as err:
        if _transient(err):
            return "transient"
        return _report(chat, _problem_of(err))
    chat.public_link = made.invite_link
    if stale is not None:
        await _retire(bot, chat, stale)
    _settled(chat)
    return "replaced" if had_link else "created"


async def sync_chat(session: AsyncSession, bot: Bot, chat: Chat) -> str:
    """`ensure_link` for one chat, stored and counted.

    The Telegram calls take a while and a person may take the chat down in the
    meantime, so the new link is written only where the row still holds the
    link and the status the work started from. Otherwise the sweep would put a
    chat the operator just unlisted back on the public page.
    """
    await session.refresh(chat)
    old = chat.public_link
    if old is None or chat.resource_status not in MANAGED_STATUSES:
        return "skipped"
    chat_id = chat.id
    outcome = await ensure_link(bot, chat)
    new = chat.public_link
    session.expire(chat)  # the change is made below, conditionally, not by the unit of work
    if new != old:
        values: dict[str, object] = {"public_link": new}
        if is_invite_link(old) and new is not None and not is_invite_link(new):
            # It turned public, and was private when its mode was given. A
            # public chat's requests come from its own setting and were always
            # the admins' to answer.
            values["join_mode"] = case((Chat.join_mode == Chat.JOIN_OPEN, Chat.JOIN_ADMINS), else_=Chat.join_mode)
        stored = await session.execute(
            update(Chat)
            .where(Chat.id == chat_id, Chat.public_link == old, Chat.resource_status.in_(MANAGED_STATUSES))
            .values(values)
        )
        await session.commit()
        if stored.rowcount == 0:  # ty: ignore[unresolved-attribute]
            if new is not None and is_invite_link(new):
                await _retire_by_id(bot, chat_id, new)
            logger.info("invite_link_dropped_chat_changed", chat_id=chat_id)
            outcome = "raced"
        else:
            logger.info("invite_link_changed", chat_id=chat_id, outcome=outcome)
    INVITE_LINK_EVENTS.labels(event=outcome).inc()
    return outcome


async def sync_once(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = PAUSE_BETWEEN_CHATS_SECONDS,
) -> dict[str, int]:
    """Check every listed chat the bot runs; returns the outcomes counted.

    Chats not listed are not published, observed ones are another bot's and
    external ones are somebody else's room the bot may not be in.
    """
    global _halted
    if _halted:
        logger.info("invite_links_halted")
        return {}
    counts: dict[str, int] = {}
    async with session_maker() as session:
        chat_ids = (
            (
                await session.execute(
                    select(Chat.id)
                    .where(Chat.resource_status.in_(MANAGED_STATUSES))
                    .where(Chat.public_link.is_not(None))
                    .order_by(Chat.id)
                )
            )
            .scalars()
            .all()
        )
    for index, chat_id in enumerate(chat_ids):
        if index:
            await asyncio.sleep(pause_seconds)
        # A session to a chat: nothing is held open across the Telegram calls of the others.
        async with session_maker() as session:
            try:
                chat = await session.get(Chat, chat_id)
                outcome = await sync_chat(session, bot, chat) if chat is not None else "skipped"
            except Exception:
                # One chat's failure is not the others': they are checked all the same.
                await session.rollback()
                logger.exception("invite_link_sync_failed", chat_id=chat_id)
                outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
        if counts.get("replaced", 0) > MAX_REPLACEMENTS_PER_SWEEP:
            _halted = True
            logger.error("invite_links_mass_replacement", replaced=counts["replaced"])
            break
    # A chat taken down or switched off is no longer a problem to be told about.
    for gone in set(_problems) - set(chat_ids):
        del _problems[gone]
    # Only those still standing, by reason, so a gauge falls when a chat recovers.
    standing = list(_problems.values())
    for reason in ("no_invite_right", "not_in_chat", "create_failed"):
        INVITE_LINK_PROBLEMS.labels(problem=reason).set(standing.count(reason))
    logger.info("invite_links_checked", **counts)
    return counts


async def run_sync_loop(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    interval_seconds: int = SYNC_INTERVAL_SECONDS,
) -> None:
    """Forever-loop, cancelled on shutdown. The first tick runs at startup, which is how old links are adopted."""
    while True:
        try:
            await sync_once(session_maker=session_maker, bot=bot)
        except Exception:
            logger.exception("invite_link_loop_iteration_failed")
        await asyncio.sleep(interval_seconds)
