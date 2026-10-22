import asyncio
import datetime

from aiogram import types
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import Message, SpamPing
from app.db.repositories import (
    get_chat_repository,
    get_message_repository,
    get_user_repository,
)


async def save_message(db: AsyncSession, message: types.Message, *, edited: bool = False) -> None:
    if not message.from_user:
        return
    chat_id = message.chat.id
    user_id = message.from_user.id
    message_id = message.message_id
    message_text = message.text or message.caption
    message_info = message.model_dump(
        exclude_defaults=True,
        exclude_none=True,
        exclude={"contact", "location", "venue", "passport_data", "web_app_data"},
    )

    message_repo = get_message_repository(db)
    await message_repo.add_message(chat_id, user_id, message_id, message_text, message_info, replace=edited)


async def merge_user(db: AsyncSession, user: types.User) -> None:
    # Only profile fields: never overwrite blocked / verify.
    await get_user_repository(db).upsert_profile(
        user.id, username=user.username, first_name=user.first_name, last_name=user.last_name
    )


async def merge_chat(db: AsyncSession, chat: types.Chat) -> None:
    chat_repo = get_chat_repository(db)
    await chat_repo.merge_chat(
        id_tg_chat=chat.id,
        title=chat.title,
        is_forum=chat.is_forum,
        is_public=chat.username is not None,
    )


logger = get_logger("moderation.history")

# Agreed with the owner on 2026-10-19 (#174): what people wrote is kept half a
# year; what a moderator marked as spam is kept for good, since the
# first-message spam check learns from it.
KEEP_DAYS = 180
_PURGE_BATCH = 5_000


async def purge_old_messages(db: AsyncSession, *, keep_days: int = KEEP_DAYS, batch: int = _PURGE_BATCH) -> int:
    """Delete recorded messages older than the retention period, spam excepted.

    In batches, committing each, so no single statement holds the table for
    the length of a backlog. Returns how many went.
    """
    cutoff = utc_now() - datetime.timedelta(days=keep_days)
    expired = (Message.timestamp < cutoff, Message.spam.is_(False))
    removed = 0
    while True:
        ids = (await db.scalars(select(Message.id).where(*expired).limit(batch))).all()
        if not ids:
            break
        # The conditions again: a row marked as spam since the select stays.
        await db.execute(delete(Message).where(Message.id.in_(ids), *expired))
        await db.commit()
        removed += len(ids)
    # Ad pings carry a snippet of what was written, so they go on the same day.
    await db.execute(delete(SpamPing).where(SpamPing.detected_at < cutoff))
    await db.commit()
    return removed


async def run_history_retention(
    session_maker: async_sessionmaker[AsyncSession], interval_seconds: int = 24 * 3600
) -> None:
    """Purge once a day, the first time an hour after start."""
    delay = 3600
    while True:
        try:
            await asyncio.sleep(delay)
            delay = interval_seconds
            async with session_maker() as session:
                removed = await purge_old_messages(session)
            logger.info("history_purged", removed=removed, keep_days=KEEP_DAYS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("history_purge_failed")
