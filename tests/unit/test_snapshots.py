"""One tick of the member-count loop, over the Bot API.

It used to read through Telethon, which meant it read through an account whose
session lives on a developer's machine — so in production it asked nobody and
wrote nothing. The moderator bot is an administrator in every managed chat and
`getChatMemberCount` is a bot method; there was never a reason for the client
API here.

Counts are taken every tick because they are the point. Title and photo are
taken once a day, because they hardly ever change and each one is another call.
"""

from __future__ import annotations

import datetime
import io
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.chats.snapshots import METADATA_STALENESS_HOURS, snapshot_once
from app.core.time import utc_now
from app.db.models import Chat, ChatAvatar, ChatMemberSnapshot
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


def _bot(
    *,
    counts: dict[int, int] | None = None,
    title: str = "Как в Telegram",
    photo: str | None = None,
    join_by_request: bool | None = None,
    username: str | None = None,
):
    """A bot that answers about every chat unless told otherwise."""
    bot = AsyncMock()
    bot.get_chat_member_count = AsyncMock(side_effect=lambda chat_id: (counts or {}).get(chat_id, 42))

    async def _get_chat(chat_id: int):
        chat = MagicMock()
        chat.title = title
        chat.photo = MagicMock(big_file_id=photo) if photo else None
        chat.join_by_request = join_by_request
        chat.username = username
        return chat

    bot.get_chat = AsyncMock(side_effect=_get_chat)
    return bot


def _bot_with_photo(big: str, small: str, unique: str):
    bot = _bot()

    async def _get_chat(chat_id):
        chat = MagicMock()
        chat.id = -100
        chat.type = "supergroup"
        chat.title = "A"
        chat.photo = MagicMock(big_file_id=big, small_file_id=small, small_file_unique_id=unique)
        return chat

    bot.get_chat = AsyncMock(side_effect=_get_chat)
    bot.download = AsyncMock(return_value=io.BytesIO(b"\xff\xd8\xff" + b"x" * 32))
    return bot


def _refused() -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message="chat not found")


async def _seed(session_maker, *chats: Chat) -> None:
    async with session_maker() as session:
        for chat in chats:
            session.add(chat)
        await session.commit()


async def _snapshots(session_maker) -> list[tuple[int, int]]:
    async with session_maker() as session:
        rows = (await session.execute(select(ChatMemberSnapshot).order_by(ChatMemberSnapshot.chat_id))).scalars().all()
    return [(row.chat_id, row.member_count) for row in rows]


async def _chat(session_maker, chat_id: int) -> Chat:
    async with session_maker() as session:
        return (await session.execute(select(Chat).where(Chat.id == chat_id))).scalar_one()


class TestCounting:
    async def test_a_row_per_chat(self, db_session_maker: async_sessionmaker[AsyncSession]) -> None:
        await _seed(db_session_maker, Chat(id=-100, title="A"), Chat(id=-200, title="B"))

        written = await snapshot_once(session_maker=db_session_maker, bot=_bot(counts={-100: 50, -200: 80}))

        assert written == 2
        assert await _snapshots(db_session_maker) == [(-200, 80), (-100, 50)]

    async def test_a_chat_telegram_will_not_answer_about_is_skipped(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Not written as zero. Zero is a claim that the room is empty."""
        await _seed(db_session_maker, Chat(id=-100, title="A"))
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(side_effect=_refused())

        written = await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert written == 0
        assert await _snapshots(db_session_maker) == []

    async def test_one_silent_chat_does_not_stop_the_rest(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """On forty-five chats, one having removed the bot is an ordinary Tuesday."""
        await _seed(db_session_maker, Chat(id=-100, title="A"), Chat(id=-200, title="B"))
        bot = _bot()

        async def _count(chat_id: int) -> int:
            if chat_id == -100:
                raise _refused()
            return 80

        bot.get_chat_member_count = AsyncMock(side_effect=_count)

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert await _snapshots(db_session_maker) == [(-200, 80)]

    async def test_counts_are_taken_even_for_a_freshly_synced_chat(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The staleness gate is about titles. The count is the reason for the tick."""
        chat = Chat(id=-100, title="A")
        chat.last_synced_at = utc_now()
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(counts={-100: 50}))

        assert await _snapshots(db_session_maker) == [(-100, 50)]


class TestMetadata:
    async def test_a_stale_title_is_refreshed(self, db_session_maker: async_sessionmaker[AsyncSession]) -> None:
        chat = Chat(id=-100, title="Старое имя")
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=METADATA_STALENESS_HOURS + 1)
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(title="Новое имя"))

        assert (await _chat(db_session_maker, -100)).title == "Новое имя"

    @pytest.mark.parametrize(("answered", "stored"), [(True, True), (None, False)])
    async def test_whether_the_chat_takes_join_requests_is_kept(
        self, db_session_maker: async_sessionmaker[AsyncSession], answered: bool | None, stored: bool
    ) -> None:
        """Telegram leaves the field out when it is off: answered without it is off, not unknown."""
        await _seed(db_session_maker, Chat(id=-100, title="A"))

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=answered))

        assert (await _chat(db_session_maker, -100)).join_by_request is stored

    async def test_a_chat_never_asked_about_join_requests_is_asked_at_once(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Synced an hour ago, before the field existed: the console needs it now, not tomorrow."""
        chat = Chat(id=-100, title="A")
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=1)
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=True))

        assert (await _chat(db_session_maker, -100)).join_by_request is True

    @pytest.mark.parametrize(("username", "settled"), [(None, Chat.JOIN_OPEN), ("public_room", Chat.JOIN_ADMINS)])
    async def test_the_first_answer_settles_a_mode_the_migration_had_to_guess(
        self, db_session_maker: async_sessionmaker[AsyncSession], username: str | None, settled: str
    ) -> None:
        """A chat with no link could be private or public; the migration chose the admins to be safe.

        A private one had the bot's link asking for no request, so once Telegram
        says it has no username it lets everyone in again, as a new chat would.
        """
        await _seed(db_session_maker, Chat(id=-100, title="A", join_mode=Chat.JOIN_ADMINS))

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=False, username=username))

        assert (await _chat(db_session_maker, -100)).join_mode == settled

    async def test_a_mode_is_not_resettled_once_the_chat_has_been_asked(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """After the first answer the admins are somebody's choice, not the migration's guess."""
        chat = Chat(id=-100, title="A", join_mode=Chat.JOIN_ADMINS)
        chat.join_by_request = False
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=False))

        assert (await _chat(db_session_maker, -100)).join_mode == Chat.JOIN_ADMINS

    async def test_a_brand_new_chat_is_synced_immediately(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """No last_synced_at means never, which is older than any cutoff."""
        await _seed(db_session_maker, Chat(id=-100, title="Как записали"))

        await snapshot_once(session_maker=db_session_maker, bot=_bot(title="Как в Telegram"))

        refreshed = await _chat(db_session_maker, -100)
        assert refreshed.title == "Как в Telegram"
        assert refreshed.last_synced_at is not None

    async def test_a_recently_synced_chat_is_not_asked_again(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Titles change about never; the call is not free."""
        chat = Chat(id=-100, title="Как записали")
        chat.last_synced_at = utc_now()
        chat.join_by_request = False
        await _seed(db_session_maker, chat)
        bot = _bot(title="Как в Telegram")

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        bot.get_chat.assert_not_awaited()
        assert (await _chat(db_session_maker, -100)).title == "Как записали"

    async def test_an_admin_edit_does_not_hold_off_a_sync(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The gate reads last_synced_at, never modified_at — otherwise editing
        the welcome text in the console would freeze the title."""
        chat = Chat(id=-100, title="Старое имя")
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=METADATA_STALENESS_HOURS + 1)
        chat.modified_at = utc_now()
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(title="Новое имя"))

        assert (await _chat(db_session_maker, -100)).title == "Новое имя"

    async def test_the_photo_is_cached(self, db_session_maker: async_sessionmaker[AsyncSession]) -> None:
        await _seed(db_session_maker, Chat(id=-100, title="A"))

        await snapshot_once(session_maker=db_session_maker, bot=_bot(photo="file-123"))

        assert (await _chat(db_session_maker, -100)).photo_file_id == "file-123"

    async def test_a_chat_that_answers_without_a_photo_has_none(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """`getChat` leaves the photo out when there is none: that is the answer, and the old one goes."""
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "file-old"
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(photo=None))

        assert (await _chat(db_session_maker, -100)).photo_file_id is None

    async def test_a_chat_that_would_not_answer_keeps_the_photo_it_had(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "file-old"
        await _seed(db_session_maker, chat)
        bot = _bot()
        bot.get_chat = AsyncMock(side_effect=_refused())

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -100)).photo_file_id == "file-old"


class TestAvatars:
    """The picture comes with the photo: fetched when it is new, not re-fetched when it is not."""

    async def _avatar(self, session_maker, chat_id: int = -100) -> ChatAvatar | None:
        async with session_maker() as session:
            return await session.get(ChatAvatar, chat_id)

    async def test_a_new_photo_is_downloaded_in_the_same_tick(self, db_session_maker) -> None:
        await _seed(db_session_maker, Chat(id=-100, title="A"))
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        avatar = await self._avatar(db_session_maker)
        assert avatar is not None
        assert avatar.unique_id == "uniq-1"

    async def test_a_chat_synced_yesterday_without_a_picture_gets_one_now(self, db_session_maker) -> None:
        """The rows that existed before this feature have a file id and no picture: waiting a day for each would be silly."""
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "big-1"
        chat.last_synced_at = utc_now()
        await _seed(db_session_maker, chat)

        await snapshot_once(session_maker=db_session_maker, bot=_bot_with_photo("big-1", "small-1", "uniq-1"))

        assert await self._avatar(db_session_maker) is not None

    async def test_a_chat_with_its_picture_is_not_asked_again_until_stale(self, db_session_maker) -> None:
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "big-1"
        chat.join_by_request = False
        chat.last_synced_at = utc_now()
        await _seed(db_session_maker, chat)
        async with db_session_maker() as session:
            session.add(ChatAvatar(chat_id=-100, unique_id="uniq-1", content=b"\xff\xd8\xff"))
            await session.commit()
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        bot.get_chat.assert_not_awaited()

    async def test_a_chat_the_bot_is_not_in_is_asked_by_its_public_name(self, db_session_maker) -> None:
        chat = Chat(id=-100, title="A", resource_status=Chat.STATUS_EXTERNAL, public_link="https://t.me/cvut_fjfi")
        await _seed(db_session_maker, chat)
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")
        by_name = bot.get_chat.side_effect

        async def _get_chat(chat_id):
            if isinstance(chat_id, int):
                raise _refused()
            return await by_name(chat_id)

        bot.get_chat = AsyncMock(side_effect=_get_chat)

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert bot.get_chat.await_args_list[-1].args == ("@cvut_fjfi",)
        assert await self._avatar(db_session_maker) is not None

    async def test_a_chat_that_removed_its_photo_loses_the_picture(self, db_session_maker) -> None:
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "big-1"
        await _seed(db_session_maker, chat)
        async with db_session_maker() as session:
            session.add(ChatAvatar(chat_id=-100, unique_id="uniq-1", content=b"\xff\xd8\xff"))
            await session.commit()

        await snapshot_once(session_maker=db_session_maker, bot=_bot(photo=None))

        assert await self._avatar(db_session_maker) is None

    async def test_a_failed_download_is_tried_again_next_tick_not_tomorrow(self, db_session_maker) -> None:
        chat = Chat(id=-100, title="A")
        chat.photo_file_id = "big-0"
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=METADATA_STALENESS_HOURS + 1)
        await _seed(db_session_maker, chat)
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")
        bot.download = AsyncMock(side_effect=_refused())
        await snapshot_once(session_maker=db_session_maker, bot=bot)
        async with db_session_maker() as session:
            session.add(ChatAvatar(chat_id=-100, unique_id="uniq-0", content=b"\xff\xd8\xff"))
            await session.commit()
        bot2 = _bot_with_photo("big-1", "small-1", "uniq-1")

        await snapshot_once(session_maker=db_session_maker, bot=bot2)

        bot2.get_chat.assert_awaited()
        avatar = await self._avatar(db_session_maker)
        assert avatar is not None
        assert avatar.unique_id == "uniq-1"

    async def test_a_download_that_fails_does_not_stop_the_tick(self, db_session_maker) -> None:
        await _seed(db_session_maker, Chat(id=-100, title="A"), Chat(id=-200, title="B"))
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")
        bot.download = AsyncMock(side_effect=_refused())

        written = await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert written == 2
        assert await self._avatar(db_session_maker) is None


class TestFloodControl:
    """Telegram answers a burst with "retry after N", and every call after it fails too.

    A tick asked about forty-six chats back to back, so after each deploy it
    lost a third of the counts to flood control.
    """

    async def test_chats_are_asked_about_one_at_a_time_with_a_pause(
        self, db_session_maker: async_sessionmaker[AsyncSession], monkeypatch
    ) -> None:
        from app.chats import snapshots

        pauses: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            pauses.append(seconds)

        monkeypatch.setattr(snapshots.asyncio, "sleep", fake_sleep)
        await _seed(db_session_maker, Chat(id=-100, title="A"), Chat(id=-200, title="B"), Chat(id=-300, title="C"))

        await snapshot_once(session_maker=db_session_maker, bot=_bot())

        assert pauses == [snapshots.PAUSE_BETWEEN_CHATS_SECONDS] * 2
        assert snapshots.PAUSE_BETWEEN_CHATS_SECONDS > 0

    async def test_a_retry_after_is_waited_out_once(self, monkeypatch) -> None:
        from aiogram.exceptions import TelegramRetryAfter
        from app.chats import metadata

        waited: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            waited.append(seconds)

        monkeypatch.setattr(metadata.asyncio, "sleep", fake_sleep)
        bot = AsyncMock()
        bot.get_chat_member_count = AsyncMock(
            side_effect=[TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=27), 120]
        )

        assert await metadata.fetch_member_count(bot=bot, chat_id=-100) == 120
        assert waited == [27]

    async def test_a_second_retry_after_gives_up(self, monkeypatch) -> None:
        from aiogram.exceptions import TelegramRetryAfter
        from app.chats import metadata

        async def fake_sleep(seconds: float) -> None:
            return None

        monkeypatch.setattr(metadata.asyncio, "sleep", fake_sleep)
        flood = TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=27)
        bot = AsyncMock()
        bot.get_chat = AsyncMock(side_effect=[flood, flood])

        assert await metadata.fetch_metadata(bot=bot, chat_id=-100) is None
        assert bot.get_chat.await_count == 2
