"""Keeping each chat's photo, so the catalog can show it.

The photo is fetched through the bot, checked, and stored in `chat_avatars`
(see the model for why the database). The web API serves it from there at an
address made from Telegram's `file_unique_id`, which changes exactly when the
chat's photo does.

Nothing here raises for a Telegram or data problem. A photo we cannot refresh is
a chat that keeps the picture it had, or the letters it started with, and the
loop over every other chat goes on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import aiohttp
from aiogram.exceptions import TelegramAPIError

from app.chats.metadata import ask
from app.core.logging import get_logger
from app.core.metrics import AVATAR_SYNCS
from app.core.time import utc_now
from app.db.models import ChatAvatar
from app.db.upsert import insert_for

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.chats.metadata import ChatMetadata
    from app.db.models import Chat

logger = get_logger("chats.avatars")

# Small chat photos are 160 px and a few kilobytes. The ceiling is a guard on
# what lands in the database, not a target: anything near it is not what we asked for.
MAX_AVATAR_BYTES = 256 * 1024
_JPEG = b"\xff\xd8\xff"

Outcome = Literal["fetched", "unchanged", "removed", "failed", "skipped"]


async def _download(bot: Bot, file_id: str) -> bytes | None:
    """The photo's bytes, or None when Telegram would not give a small JPEG."""
    try:
        buffer = await ask(lambda: bot.download(file_id))
    except TelegramAPIError as err:
        logger.warning("avatar_download_failed", error=str(err), error_type=type(err).__name__)
        return None
    except (aiohttp.ClientError, TimeoutError) as err:
        # The file server is plain HTTP, and the text of its errors is the URL,
        # which has the bot token in it: the kind of failure is all that is logged.
        logger.warning(
            "avatar_download_failed",
            error_type=type(err).__name__,
            status=getattr(err, "status", None),
        )
        return None
    if buffer is None:
        return None
    data = buffer.read()
    # Served to strangers under our own address with a content type we choose, so
    # only what really is a JPEG of the expected size gets that far.
    if not data.startswith(_JPEG) or len(data) >= MAX_AVATAR_BYTES:
        logger.warning("avatar_rejected", size=len(data))
        return None
    return data


async def sync_photo(*, session: AsyncSession, bot: Bot, chat: Chat, metadata: ChatMetadata) -> Outcome:
    """Bring the stored photo in line with what Telegram just said. Caller commits.

    `metadata` must be a real answer: one without a photo means the chat has none
    now, and its stored picture is removed. Not having an answer is the caller's
    to handle by not calling this.
    """
    outcome = await _sync(session=session, bot=bot, chat=chat, metadata=metadata)
    AVATAR_SYNCS.labels(outcome=outcome).inc()
    if outcome != "unchanged":
        logger.info("avatar_synced", chat_id=chat.id, outcome=outcome)
    return outcome


async def _sync(*, session: AsyncSession, bot: Bot, chat: Chat, metadata: ChatMetadata) -> Outcome:
    stored = await session.get(ChatAvatar, chat.id)

    if metadata.photo_file_id is None:
        chat.photo_file_id = None
        if stored is None:
            return "unchanged"
        await session.delete(stored)
        return "removed"

    chat.photo_file_id = metadata.photo_file_id
    if metadata.avatar_file_id is None or metadata.avatar_unique_id is None:
        return "skipped"
    if stored is not None and stored.unique_id == metadata.avatar_unique_id:
        return "unchanged"

    data = await _download(bot, metadata.avatar_file_id)
    if data is None:
        return "failed"
    # An upsert, because the hourly tick, the console's refresh and the photo
    # handler can each be putting a chat's first picture in at once.
    insert = insert_for(session, ChatAvatar.__table__).values(
        chat_id=chat.id,
        unique_id=metadata.avatar_unique_id,
        content=data,
        content_type="image/jpeg",
        fetched_at=utc_now(),
    )
    await session.execute(
        insert.on_conflict_do_update(
            index_elements=["chat_id"],
            set_={name: insert.excluded[name] for name in ("unique_id", "content", "content_type", "fetched_at")},
        )
    )
    if stored is not None:
        session.expire(stored)
    return "fetched"
