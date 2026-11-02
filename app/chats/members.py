"""What each person is in each chat, kept as Telegram reports it.

The one writer of `chat_members`. Telegram sends the bot an update whenever
somebody joins, leaves, is banned, muted, promoted or demoted in a chat where
the bot is an administrator, and that update is the source. Nothing else
writes here: a ban or a mute the bot itself makes comes back as the same
update, so moderation never records the result twice.

Updates miss what changed while the bot was down. Members are too many to
ask about one by one, so only administrators are checked, once a day with
the bot's own rights: `getChatAdministrators`, which leaves bots out, and
`getChatMember` for anybody stored as an administrator who is no longer on
that list. A chat thus costs two calls a day and one more per stored
administrator off the list; another bot that is an administrator is never
on it, so is asked about every day. Bots no update named are not known at
all: the full list of them takes a user account.

A restriction or a ban that runs out sends no update: `until_date` is to be
compared with now, never taken as still in force.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy import select

from app.chats.metadata import ask
from app.core.logging import get_logger
from app.core.time import as_naive_utc
from app.db.models import ChatMember
from app.db.upsert import insert_for

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import ChatMemberUnion
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger("chats.members")

ADMINISTRATORS = ("administrator", "creator")


def status_of(member: ChatMemberUnion) -> str:
    """Telegram's word for it; aiogram hands it over as an enum, whose str() is the enum's name."""
    return str(getattr(member.status, "value", member.status))


def rights_of(member: ChatMemberUnion) -> dict[str, bool]:
    """Every true-or-false field Telegram gave, under its own names.

    A right Telegram left out is left out here too: it omits `can_manage_tags`
    when it equals `can_pin_messages`, and guessing would record a change
    Telegram never made.
    """
    return {name: value for name, value in member.model_dump().items() if isinstance(value, bool)}


def _until(member: ChatMemberUnion) -> datetime.datetime | None:
    until = getattr(member, "until_date", None)
    # Telegram's 0 is "for good", which aiogram turns into the epoch.
    if not isinstance(until, datetime.datetime) or until.timestamp() <= 0:
        return None
    return as_naive_utc(until)


async def record(
    db: AsyncSession,
    chat_id: int,
    member: ChatMemberUnion,
    *,
    at: datetime.datetime,
    update_id: int | None = None,
) -> None:
    """Take what Telegram said `member` is in `chat_id` at `at`, and commit.

    An update older than what is stored changes nothing. Telegram's times are
    whole seconds, and the captcha mutes and then admits within one, so in
    the same second the later update (Telegram numbers them in order) wins;
    the daily check has no number and takes the second only from nothing.
    The first state is inserted in one statement, as with the bot's own
    rights: a join and a promotion arrive as two updates handled at once.
    """
    status, rights, until = status_of(member), rights_of(member), _until(member)
    created = await db.execute(
        insert_for(db, ChatMember)
        .values(
            chat_id=chat_id,
            user_id=member.user.id,
            status=status,
            rights=rights,
            until_date=until,
            changed_at=at,
            known_at=at,
            update_id=update_id,
        )
        .on_conflict_do_nothing(index_elements=[ChatMember.chat_id, ChatMember.user_id])
        .returning(ChatMember.user_id)
    )
    if created.first() is not None:
        await db.commit()
        return
    row = await db.get(ChatMember, (chat_id, member.user.id), with_for_update=True, populate_existing=True)
    if row is None or row.known_at > at or (row.known_at == at and _earlier(update_id, row.update_id)):
        await db.rollback()
        return
    if (row.status, row.rights, row.until_date) != (status, rights, until):
        row.status, row.rights, row.until_date, row.changed_at = status, rights, until, at
    row.known_at, row.update_id = at, update_id
    await db.commit()


def _earlier(update_id: int | None, stored: int | None) -> bool:
    """Whether an update from the same second as the stored state is older than it.

    Without a number on either side (the daily check) there is no telling:
    the stored state stays.
    """
    return update_id is None or (stored is not None and update_id < stored)


async def check_administrators(
    *, session_maker: async_sessionmaker[AsyncSession], bot: Bot, chat_id: int, at: datetime.datetime
) -> None:
    """Bring the chat's administrators up to date. Raises what Telegram raises; the caller paces and decides.

    `at` is when the caller started asking, in whole seconds, so an update
    that came in meanwhile still counts as newer.
    """
    admins = await ask(lambda: bot.get_chat_administrators(chat_id))
    async with session_maker() as session:
        for admin in admins:
            await record(session, chat_id, admin, at=at)
        listed = {admin.user.id for admin in admins} | {bot.id}
        stale = (
            await session.scalars(
                select(ChatMember.user_id)
                .where(
                    ChatMember.chat_id == chat_id,
                    ChatMember.status.in_(ADMINISTRATORS),
                    ChatMember.user_id.not_in(listed),
                )
                .order_by(ChatMember.user_id)
            )
        ).all()
    # Off the list: demoted, gone, or a bot, which the list never shows.
    for user_id in stale:
        try:
            member = await ask(lambda user_id=user_id: bot.get_chat_member(chat_id, user_id))
        except TelegramRetryAfter:
            raise
        except TelegramAPIError as err:
            # One person Telegram will not answer about must not hide the rest until tomorrow.
            logger.warning(
                "administrator_check_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=str(err),
                error_type=type(err).__name__,
            )
            continue
        async with session_maker() as session:
            await record(session, chat_id, member, at=at)
