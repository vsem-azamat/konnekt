"""Periodic member-count snapshots, over the Bot API.

Runs as one background task in the bot process. It used to read through the
Telethon client and had never written a row: that client is a per-process
singleton wired at the bot's startup, the loop was started from the web API,
and the account's session lives on a developer's machine rather than on the
server. The client API was never needed here — the moderator bot is an
administrator in every managed chat, and `getChatMemberCount` is a bot method.

Intentionally simple: two calls per chat per tick (a public chat the bot is
not in: two more by its name, once a day), no concurrency, no deduplication.
If the process dies we lose the in-flight tick and nothing is corrupted,
because each snapshot is an independent row.

Each tick also refreshes the title and photo of chats whose ``last_synced_at``
is older than ``METADATA_STALENESS_HOURS``. That check uses ``last_synced_at``
and not ``modified_at``, so an admin's edit in the console does not suppress a
Telegram sync and a Telegram sync does not masquerade as an admin's edit.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

import aiohttp
from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import select, update

from app.chats import previews
from app.chats.avatars import sync_photo
from app.chats.metadata import (
    BotNotInChatError,
    ChatMigratedError,
    fetch_member_count,
    fetch_member_count_by_name,
    fetch_metadata,
    fetch_metadata_by_name,
    username_of,
)
from app.chats.migration import follow_upgrade
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Chat, ChatAvatar, ChatMemberSnapshot

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.snapshots")

SNAPSHOT_INTERVAL_SECONDS = 3600  # 1 hour
# Asked back to back, forty-six chats tripped flood control after every deploy
# and lost a third of the counts. A second apart, a tick takes under a minute
# of an hour.
PAUSE_BETWEEN_CHATS_SECONDS = 1.0
METADATA_STALENESS_HOURS = 24
# A chat the bot is not in answers the same "chat not found" every hour. Asked
# once a day it still comes back by itself once somebody adds the bot, which
# the bot is not told about for a chat outside the approval gate.
BOT_ABSENT_RECHECK_HOURS = 24


def _apply_title(chat: Chat, title: str | None) -> bool:
    """Take Telegram's title. True when it actually differed.

    Only the title, because it is the one upstream-managed string the console
    shows; welcome text, captcha, parent and notes are the admin's and must not
    be overwritten by a sync.
    """
    if not title or title == chat.title:
        return False
    chat.title = title
    return True


async def _settle_guessed_mode(session_maker: async_sessionmaker[AsyncSession], chat_id: int, *, public: bool) -> None:
    """Settle the admins the migration gave a chat for want of a link.

    A private chat had the bot's link asking for no request, as a new private
    chat is given now. Written only where nobody has set a mode since this run
    read the row: the first run after the deploy asks every chat while
    operators are at work. Committed on its own: the run's transaction lasts
    minutes, and the bot's every update from the chat would wait on the row.
    """
    async with session_maker() as session:
        await session.execute(
            update(Chat)
            .where(Chat.id == chat_id, Chat.join_mode_guessed.is_(True), Chat.join_mode == Chat.JOIN_ADMINS)
            .values(join_mode=Chat.JOIN_ADMINS if public else Chat.JOIN_OPEN, join_mode_guessed=False)
        )
        await session.commit()


def _note_absent(chat: Chat, now: datetime.datetime) -> None:
    """Mark a chat the bot is not in, saying so once rather than every hour.

    Most likely the chat was never added to the current bot: on 2026-10-20 the
    moderator moved to a new bot, and only the chats it was added to know it.
    """
    if chat.bot_absent_at is None:
        logger.warning(
            "bot_not_in_chat",
            chat_id=chat.id,
            title=chat.title,
            status=chat.resource_status,
            hint="Telegram does not know this chat to the current bot: most likely never added after the bot moved",
            recheck_hours=BOT_ABSENT_RECHECK_HOURS,
        )
    else:
        logger.info("bot_still_not_in_chat", chat_id=chat.id)
    chat.bot_absent_at = now


async def snapshot_once(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> int:
    """Record one member count per chat. Returns how many rows were written.

    A chat Telegram will not answer about is skipped rather than written as
    zero, and the rest of the tick continues — on forty-five chats, one of them
    having removed the bot is an ordinary Tuesday.
    """
    written = 0
    refreshed = 0
    photo_refreshed = 0
    now = utc_now()
    cutoff = now - datetime.timedelta(hours=METADATA_STALENESS_HOURS)
    absent_cutoff = now - datetime.timedelta(hours=BOT_ABSENT_RECHECK_HOURS)

    async with session_maker() as session:
        everything = (await session.execute(select(Chat))).scalars().all()
        # A chat known only by its invite link is not Telegram's to answer
        # about to this bot: its page is read instead, once a day. A group that
        # became a supergroup answers nothing about its old id again.
        chats = [chat for chat in everything if not chat.is_preview_only and chat.migrated_to_chat_id is None]
        previewed = [
            chat
            for chat in everything
            if chat.is_preview_only and (chat.last_synced_at is None or chat.last_synced_at < cutoff)
        ]
        pictured = set((await session.execute(select(ChatAvatar.chat_id))).scalars())
        asked = 0
        # One long flood wait on a lookup by name ends them for the tick: the
        # next would only add to it. A chat the bot is not in that lost its
        # turn to the flood waits for its next daily one.
        by_name_flooded = False
        for chat in chats:
            if chat.bot_absent_at is not None and chat.bot_absent_at > absent_cutoff:
                continue
            if asked:
                await asyncio.sleep(PAUSE_BETWEEN_CHATS_SECONDS)
            asked += 1
            username = username_of(chat.public_link) if chat.public_link else None
            metadata = None
            try:
                members = await fetch_member_count(bot=bot, chat_id=chat.id)
            except ChatMigratedError as err:
                logger.info("chat_migrated", chat_id=chat.id, to_chat_id=err.new_chat_id)
                chat.migrated_to_chat_id = err.new_chat_id
                continue
            except BotNotInChatError:
                _note_absent(chat, now)
                # A public chat still answers by its name, as rarely as the id
                # is asked: its title and photo, and its size once the name is
                # known to be still this chat's. A private one has nothing more to say.
                if username is None or by_name_flooded:
                    continue
                try:
                    metadata = await fetch_metadata_by_name(bot=bot, chat_id=chat.id, username=username)
                except TelegramRetryAfter as err:
                    logger.warning("lookup_by_name_flooded", chat_id=chat.id, retry_after=err.retry_after)
                    by_name_flooded = True
                    continue
                if metadata is None:
                    continue
                try:
                    members = await fetch_member_count_by_name(bot=bot, chat_id=chat.id, username=username)
                except TelegramRetryAfter as err:
                    # The title and photo already came; only the count is lost.
                    logger.warning("lookup_by_name_flooded", chat_id=chat.id, retry_after=err.retry_after)
                    by_name_flooded = True
                    members = None
            else:
                # Only a count says the bot is back: a timeout says nothing.
                if members is not None and chat.bot_absent_at is not None:
                    logger.info("bot_back_in_chat", chat_id=chat.id)
                    chat.bot_absent_at = None
            if members is not None:
                session.add(ChatMemberSnapshot(chat_id=chat.id, member_count=members))
                written += 1

            if metadata is None:
                # A chat with a photo and no picture is asked about at once rather
                # than at its next daily turn: the rows that existed before pictures
                # were kept, and one whose download failed, are all in that state.
                unpictured = chat.photo_file_id is not None and chat.id not in pictured
                # Likewise a chat never asked whether it takes join requests.
                unasked = chat.join_by_request is None or chat.join_mode_guessed
                if not unpictured and not unasked and chat.last_synced_at is not None and chat.last_synced_at >= cutoff:
                    continue
                metadata = await fetch_metadata(
                    bot=bot, chat_id=chat.id, username=None if by_name_flooded else username
                )
                if metadata is None:
                    continue
            if _apply_title(chat, metadata.title):
                refreshed += 1
            if chat.join_mode_guessed:
                await _settle_guessed_mode(session_maker, chat.id, public=metadata.username is not None)
            chat.join_by_request = metadata.join_by_request
            outcome = await sync_photo(session=session, bot=bot, chat=chat, metadata=metadata)
            if outcome in {"fetched", "removed"}:
                photo_refreshed += 1
            if outcome != "failed":
                # A picture that could not be fetched leaves the chat due, so the next
                # tick tries again (a chat the bot is not in, at its next daily turn).
                chat.last_synced_at = now

        if previewed:
            async with aiohttp.ClientSession() as http:
                for chat in previewed:
                    try:
                        async with session.begin_nested():
                            read = await previews.sync(session, http, chat)
                    except Exception:
                        # One bad page must not undo the hour's work for every other chat.
                        logger.exception("preview_sync_failed", chat_id=chat.id)
                        continue
                    if read is not None and read.member_count is not None:
                        written += 1

        # Telegram announces an upgrade once, in a message the bot may have
        # missed; what it says here is the same fact, so the chat is followed all
        # the same. A follow that failed or never ran is still pending next hour:
        # a followed row is always disabled.
        upgraded = [
            (chat.id, chat.migrated_to_chat_id)
            for chat in everything
            if chat.migrated_to_chat_id is not None and chat.resource_status != Chat.STATUS_DISABLED
        ]
        await session.commit()

    for old_id, new_id in upgraded:
        await _follow(session_maker, old_id=old_id, new_id=new_id)

    logger.info(
        "snapshot_once committed",
        snapshots=written,
        metadata_refreshed=refreshed,
        photo_refreshed=photo_refreshed,
    )
    return written


async def _follow(session_maker: async_sessionmaker[AsyncSession], *, old_id: int, new_id: int) -> None:
    async with session_maker() as session:
        try:
            await follow_upgrade(session, old_id=old_id, new_id=new_id)
        except Exception:
            # The old row stays marked, so nobody asks Telegram about it again,
            # and the next run tries the follow once more.
            await session.rollback()
            logger.exception("chat_upgrade_not_followed", old_id=old_id, new_id=new_id)


async def run_snapshot_loop(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    bot: Bot,
    interval_seconds: int = SNAPSHOT_INTERVAL_SECONDS,
) -> None:
    """Forever-loop. Cancelled on shutdown via task.cancel().

    No waiting for anything to connect: the bot token works from the first
    call, which is most of the point of having moved off the client API.
    """
    while True:
        try:
            await snapshot_once(session_maker=session_maker, bot=bot)
        except Exception:
            logger.exception("snapshot_loop iteration failed")
        await asyncio.sleep(interval_seconds)
