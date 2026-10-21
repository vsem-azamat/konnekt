import asyncio
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import SpamVerdict
from app.core.exceptions import NotAPersonError, ProtectedUserError
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import SpamPing
from app.db.repositories import (
    ChatRepository,
    MessageRepository,
    UserRepository,
)

logger = get_logger("moderation")


# Telegram's stand-ins on messages no person signed: posts sent as a channel,
# anonymous admins, and posts forwarded from a linked channel. Each is shared by
# every such message, so acting on one acts on all of them, everywhere.
STAND_IN_SENDERS = frozenset({136817688, 1087968824, 777000})


def is_stand_in(user_id: int) -> bool:
    return user_id in STAND_IN_SENDERS


def is_protected(user_id: int) -> bool:
    """A super admin: never blacklisted, by any caller.

    A blacklisted account loses every message, its private ones to the bot
    included, so a super admin on the list would lose the bot itself.
    """
    return user_id in settings.admin.super_admins


async def approved_chat_ids(db: AsyncSession) -> list[int]:
    """The chats a blacklist entry acts in.

    The bot records every group it sits in, other people's included; acting in
    one nobody approved overrules its owner (docs/invariants.md, Approval).
    """
    return [chat.id for chat in await ChatRepository(db).get_chats() if chat.is_approved]


# Telegram's flood control: the member-count loop found that 46 calls back to
# back tripped it and lost a third of them.
_FAN_OUT_CONCURRENCY = 4
_FAN_OUT_ATTEMPTS = 3


async def _fan_out(
    chat_ids: list[int], call: Callable[[int], Awaitable[object]], *, what: str, user_id: int
) -> list[int]:
    """Run `call` in every chat, a few at a time, waiting out flood control.

    Returns the chats where it still failed. Those were logged as "maybe
    already banned" and forgotten, so a blacklisted person stayed in some chats
    and an unblacklisted one stayed out of others; now they are named, and an
    incomplete fan-out is an error, which reaches the report chat.
    """
    gate = asyncio.Semaphore(_FAN_OUT_CONCURRENCY)

    async def in_chat(chat_id: int) -> int | None:
        async with gate:
            for attempt in range(1, _FAN_OUT_ATTEMPTS + 1):
                try:
                    await call(chat_id)
                    return None
                except TelegramRetryAfter as err:
                    if attempt == _FAN_OUT_ATTEMPTS:
                        logger.warning(f"{what}_flood_control", user_id=user_id, chat_id=chat_id)
                        break
                    await asyncio.sleep(err.retry_after)
                except Exception as err:
                    logger.warning(
                        f"{what}_failed",
                        user_id=user_id,
                        chat_id=chat_id,
                        error=str(err),
                        error_type=type(err).__name__,
                    )
                    return chat_id
            return chat_id

    failed = [chat_id for chat_id in await asyncio.gather(*(in_chat(c) for c in chat_ids)) if chat_id is not None]
    if failed:
        logger.error(f"{what}_incomplete", user_id=user_id, failed_chats=failed, chats=len(chat_ids))
    return failed


async def add_to_blacklist(
    db: AsyncSession,
    bot: Bot,
    id_tg: int,
    revoke_messages: bool | None = None,
    *,
    actor_id: int | None = None,
) -> list[int]:
    """Blacklist somebody and ban them from every approved chat; returns where the ban failed.

    ``actor_id`` is who asked, recorded on the ad hits the ban answers.
    """
    if is_protected(id_tg):
        raise ProtectedUserError(id_tg)
    if is_stand_in(id_tg):
        raise NotAPersonError(id_tg)
    user_repo = UserRepository(db)
    message_repo = MessageRepository(db)
    await user_repo.add_to_blacklist(id_tg)
    approved = await approved_chat_ids(db)

    failed = await _fan_out(
        approved,
        lambda chat_id: bot.ban_chat_member(chat_id, id_tg, revoke_messages=revoke_messages),
        what="blacklist_ban",
        user_id=id_tg,
    )
    if len(failed) < len(approved):
        await _answer_ad_hits(db, id_tg, actor_id)

    if not revoke_messages:
        return failed

    # Deliberately outside the fan-out above. Every recorded message names the
    # one chat it was written in, so deleting it there is a single call — but
    # nested inside a loop over chats it became that call once per chat, which
    # on forty-five chats and a few hundred messages is thousands of requests,
    # all but a fraction of them doomed, spent while an administrator waits for
    # a spammer to disappear.
    for message in await message_repo.get_user_messages(id_tg):
        # A group counts only when approved; a message whose group has no row
        # (older history) stays. The private chat with the bot is not a group.
        if message.chat_id < 0 and message.chat_id not in approved:
            continue
        try:
            await bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        except Exception as err:
            # Telegram refuses routinely here — a message already gone, or older
            # than it allows. One refusal says nothing about the next.
            logger.warning(
                "message_delete_failed",
                user_id=id_tg,
                chat_id=message.chat_id,
                message_id=message.message_id,
                error_type=type(err).__name__,
            )
    return failed


async def _answer_ad_hits(db: AsyncSession, id_tg: int, actor_id: int | None) -> None:
    """A ban that took somewhere is the verdict on every hit of theirs still
    waiting in the console's queue. Lifting it later leaves them answered."""
    await db.execute(
        update(SpamPing)
        .where(SpamPing.user_id == id_tg, SpamPing.verdict.is_(None))
        .values(verdict=SpamVerdict.AD, reviewed_at=utc_now(), reviewed_by=actor_id)
    )
    await db.commit()


async def remove_from_blacklist(db: AsyncSession, bot: Bot, id_tg: int) -> list[int]:
    """Take somebody off the blacklist and unban them everywhere; returns where the unban failed."""
    user_repo = UserRepository(db)

    await user_repo.remove_from_blacklist(id_tg)
    approved = await approved_chat_ids(db)

    return await _fan_out(
        approved,
        # Without only_if_banned, Telegram removes a current member.
        lambda chat_id: bot.unban_chat_member(chat_id, id_tg, only_if_banned=True),
        what="blacklist_unban",
        user_id=id_tg,
    )
