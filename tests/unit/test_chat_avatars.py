"""Keeping a chat's photo as bytes we serve ourselves.

A Telegram file id cannot be shown to a browser and the download URL carries the
bot token, so the photo is fetched once, kept, and served from our own address.
What is pinned here is when it is fetched again (only when Telegram says the
photo is a different one), and that nothing which fails can leave a chat with a
broken picture instead of the letters it had.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.chats.avatars import MAX_AVATAR_BYTES, sync_photo
from app.chats.metadata import ChatMetadata
from app.db.models import Chat, ChatAvatar

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64
CHAT = -1001


def _meta(unique: str | None = "uniq-1", small: str | None = "small-1", big: str | None = "big-1") -> ChatMetadata:
    return ChatMetadata(title="T", photo_file_id=big, avatar_file_id=small, avatar_unique_id=unique)


def _bot(data: bytes | None = JPEG) -> AsyncMock:
    bot = AsyncMock()
    bot.download = AsyncMock(return_value=io.BytesIO(data) if data is not None else None)
    return bot


async def _run(session_maker, bot, metadata, chat_id: int = CHAT) -> tuple[str, Chat, ChatAvatar | None]:
    async with session_maker() as session:
        chat = await session.get(Chat, chat_id)
        assert chat is not None
        outcome = await sync_photo(session=session, bot=bot, chat=chat, metadata=metadata)
        await session.commit()
    async with session_maker() as session:
        chat = await session.get(Chat, chat_id)
        avatar = await session.get(ChatAvatar, chat_id)
    assert chat is not None
    return outcome, chat, avatar


@pytest.fixture
async def seeded(db_session_maker: async_sessionmaker[AsyncSession]):
    async with db_session_maker() as session:
        session.add(Chat(id=CHAT, title="T"))
        await session.commit()
    return db_session_maker


async def test_a_new_photo_is_downloaded_and_kept(seeded) -> None:
    bot = _bot()
    outcome, chat, avatar = await _run(seeded, bot, _meta())

    assert outcome == "fetched"
    bot.download.assert_awaited_once_with("small-1")
    assert avatar is not None
    assert (avatar.unique_id, avatar.content, avatar.content_type) == ("uniq-1", JPEG, "image/jpeg")
    assert chat.photo_file_id == "big-1"


async def test_the_same_photo_is_not_downloaded_again(seeded) -> None:
    await _run(seeded, _bot(), _meta())
    bot = _bot()
    outcome, _chat, avatar = await _run(seeded, bot, _meta())

    assert outcome == "unchanged"
    bot.download.assert_not_awaited()
    assert avatar is not None
    assert avatar.unique_id == "uniq-1"


async def test_a_changed_photo_replaces_the_old_one(seeded) -> None:
    await _run(seeded, _bot(), _meta())
    new = JPEG + b"new"
    outcome, chat, avatar = await _run(seeded, _bot(new), _meta(unique="uniq-2", small="small-2", big="big-2"))

    assert outcome == "fetched"
    assert avatar is not None
    assert (avatar.unique_id, avatar.content) == ("uniq-2", new)
    assert chat.photo_file_id == "big-2"


async def test_a_removed_photo_drops_the_stored_one(seeded) -> None:
    await _run(seeded, _bot(), _meta())
    outcome, chat, avatar = await _run(seeded, _bot(), _meta(unique=None, small=None, big=None))

    assert outcome == "removed"
    assert avatar is None
    assert chat.photo_file_id is None


async def test_a_chat_that_never_had_one_is_unchanged(seeded) -> None:
    outcome, _chat, avatar = await _run(seeded, _bot(), _meta(unique=None, small=None, big=None))

    assert outcome == "unchanged"
    assert avatar is None


class TestFailureKeepsWhatWeHad:
    async def test_a_refused_download_keeps_the_old_picture(self, seeded) -> None:
        await _run(seeded, _bot(), _meta())
        bot = AsyncMock()
        bot.download = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="file is temporarily unavailable")
        )
        outcome, _chat, avatar = await _run(seeded, bot, _meta(unique="uniq-2"))

        assert outcome == "failed"
        assert avatar is not None
        assert avatar.unique_id == "uniq-1"

    @pytest.mark.parametrize(
        "payload",
        [None, b"", b"<html>not a picture</html>", b"\xff\xd8\xff" + b"x" * MAX_AVATAR_BYTES],
        ids=["nothing", "empty", "not-a-jpeg", "too-big"],
    )
    async def test_what_is_not_a_small_jpeg_is_not_stored(self, seeded, payload) -> None:
        outcome, _chat, avatar = await _run(seeded, _bot(payload), _meta())

        assert outcome == "failed"
        assert avatar is None

    async def test_a_photo_without_a_small_size_is_left_to_a_later_tick(self, seeded) -> None:
        bot = _bot()
        outcome, chat, avatar = await _run(seeded, bot, _meta(unique=None, small=None, big="big-1"))

        assert outcome == "skipped"
        bot.download.assert_not_awaited()
        assert avatar is None
        assert chat.photo_file_id == "big-1"
