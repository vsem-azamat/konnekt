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
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy import select

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
# Chats the bot is in and lists as its own; external ones are somebody else's room.
MANAGED_STATUSES = (Chat.STATUS_APPROVED, Chat.STATUS_OBSERVED)
SYNC_INTERVAL_SECONDS = 900
# One edit and one lookup per chat; a second apart keeps a tick clear of flood control.
PAUSE_BETWEEN_CHATS_SECONDS = 1.0

# The chats whose link the bot cannot mend, and why: the one memory that keeps
# a standing problem from being reported again every tick. Per process; a
# restart reports what is still broken once more, which is the right reminder.
_problems: dict[int, str] = {}


def forget_problems() -> None:
    _problems.clear()


def is_invite_link(link: str) -> bool:
    """A `t.me/+hash` or `joinchat` link, as opposed to a username."""
    tail = link.rstrip("/").rsplit("/", 1)[-1]
    return tail.startswith("+") or "joinchat" in link


def _usable(link: ChatInviteLink) -> bool:
    """Whether a link Telegram just edited is one a stranger can still join by.

    Ours never carry a limit or an expiry, so one that does was not made by
    this module and would stop working under the catalogue sooner or later:
    replaced now, rather than when someone finds the page's link dead.
    """
    return not link.is_revoked and link.member_limit is None and link.expire_date is None


def _transient(err: TelegramAPIError) -> bool:
    return isinstance(err, TelegramRetryAfter | TelegramNetworkError | TelegramServerError)


def _problem_of(err: TelegramAPIError) -> str:
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
        logger.error("invite_link_unrecoverable", chat_id=chat.id, problem=problem)
    else:
        logger.info("invite_link_still_broken", chat_id=chat.id, problem=problem)
    return problem


def _settled(chat: Chat) -> None:
    if _problems.pop(chat.id, None) is not None:
        logger.info("invite_link_recovered", chat_id=chat.id)


async def _retire(bot: Bot, chat: Chat, link: str) -> None:
    """Revoke a link of ours that nothing serves any more; never at the cost of the caller."""
    try:
        await bot.revoke_chat_invite_link(chat_id=chat.id, invite_link=link)
    except TelegramAPIError as err:
        logger.info("invite_link_not_retired", chat_id=chat.id, error=str(err), error_type=type(err).__name__)


async def ensure_link(bot: Bot, chat: Chat) -> str:
    """Make `chat.public_link` a link that works; returns what was done.

    The caller commits. Outcomes: `kept`, `created`, `replaced`, `username`,
    `transient` (nothing known, nothing changed), or a problem the bot cannot
    mend (`no_invite_right`, `not_in_chat`, `create_failed`).
    """
    try:
        info = await ask(lambda: bot.get_chat(chat.id))
    except TelegramAPIError as err:
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
            await _retire(bot, chat, current)
        _settled(chat)
        return "username"

    # A chat that has the bot's captcha, or admits only by request, must not
    # hand out a link that skips the check.
    wants_request = chat.is_captcha_enabled or bool(info.join_by_request)

    had_link = current is not None and is_invite_link(current)
    if had_link:
        assert current is not None
        try:
            edited = await ask(
                lambda: bot.edit_chat_invite_link(
                    chat_id=chat.id, invite_link=current, name=LINK_NAME, creates_join_request=wants_request
                )
            )
        except TelegramAPIError as err:
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
            await _retire(bot, chat, current)

    try:
        made = await ask(
            lambda: bot.create_chat_invite_link(chat_id=chat.id, name=LINK_NAME, creates_join_request=wants_request)
        )
    except TelegramAPIError as err:
        if _transient(err):
            return "transient"
        return _report(chat, _problem_of(err))
    chat.public_link = made.invite_link
    _settled(chat)
    return "replaced" if had_link else "created"


async def sync_chat(session: AsyncSession, bot: Bot, chat: Chat) -> str:
    """`ensure_link` for one chat, stored and counted."""
    outcome = await ensure_link(bot, chat)
    INVITE_LINK_EVENTS.labels(event=outcome).inc()
    if outcome in {"created", "replaced", "username"}:
        await session.commit()
        logger.info("invite_link_changed", chat_id=chat.id, outcome=outcome)
    return outcome


async def sync_once(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    pause_seconds: float = PAUSE_BETWEEN_CHATS_SECONDS,
) -> dict[str, int]:
    """Check every listed chat the bot is in; returns the outcomes counted.

    Chats we only list as somebody else's (`external`) are not ours to link
    and the bot is not necessarily in them; chats not listed are not published.
    """
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
            try:
                # Read afresh: a rollback below expires everything still held.
                chat = await session.get(Chat, chat_id)
                if chat is None:
                    continue
                outcome = await sync_chat(session, bot, chat)
            except Exception:
                # One chat's failure is not the others': they are checked all the same.
                await session.rollback()
                logger.exception("invite_link_sync_failed", chat_id=chat_id)
                outcome = "failed"
            counts[outcome] = counts.get(outcome, 0) + 1
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
