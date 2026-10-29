"""A person's Telegram photo, for the console's faces.

Asked of Telegram the first time the console shows someone and kept in
`user_photos` for a week, an empty answer included. A failed question is not
kept, so the next look asks again; until then the console shows the person's
letters, as it does for someone without a photo.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError

from app.chats.avatars import download_small_jpeg
from app.chats.metadata import ask
from app.core.logging import get_logger
from app.core.time import utc_now
from app.db.models import UserPhoto
from app.db.upsert import insert_for

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import PhotoSize
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("people.photos")

# A changed photo shows within a week; a sooner answer is the cost of a call per face.
FRESH_FOR = datetime.timedelta(days=7)

# The size Telegram makes for lists: 160 px, enough for the largest face at 56.
SMALL = 160

# A page of fifty new faces asks a few at a time, not fifty at once into flood control.
_asking = asyncio.Semaphore(4)


async def photo_of(session: AsyncSession, bot: Bot, user_id: int) -> bytes | None:
    """The person's photo as a JPEG, or None for their letters. Caller commits."""
    stored = await session.get(UserPhoto, user_id)
    if stored is not None and utc_now() - stored.fetched_at < FRESH_FOR:
        return stored.content
    async with _asking:
        try:
            answer = await ask(lambda: bot.get_user_profile_photos(user_id, limit=1))
        except TelegramAPIError as err:
            logger.warning("user_photo_failed", user_id=user_id, error_type=type(err).__name__)
            return stored.content if stored is not None else None
        size = _small(answer.photos[0]) if answer.photos else None
        if size is None:
            await _keep(session, user_id, unique_id=None, content=None)
            return None
        if stored is not None and stored.unique_id == size.file_unique_id:
            await _keep(session, user_id, unique_id=stored.unique_id, content=stored.content)
            return stored.content
        content = await download_small_jpeg(bot, size.file_id)
    if content is None:
        return stored.content if stored is not None else None
    await _keep(session, user_id, unique_id=size.file_unique_id, content=content)
    return content


def _small(sizes: list[PhotoSize]) -> PhotoSize | None:
    """The smallest size that is not smaller than a list's, else the largest there is."""
    if not sizes:
        return None
    big_enough = [size for size in sizes if size.width >= SMALL]
    return min(big_enough, key=lambda size: size.width) if big_enough else max(sizes, key=lambda size: size.width)


async def _keep(session: AsyncSession, user_id: int, *, unique_id: str | None, content: bytes | None) -> None:
    # An upsert: two tabs showing the same new face put its first row in at once.
    insert = insert_for(session, UserPhoto.__table__).values(
        user_id=user_id,
        unique_id=unique_id,
        content=content,
        content_type="image/jpeg",
        fetched_at=utc_now(),
    )
    await session.execute(
        insert.on_conflict_do_update(
            index_elements=["user_id"],
            set_={name: insert.excluded[name] for name in ("unique_id", "content", "content_type", "fetched_at")},
        )
    )
