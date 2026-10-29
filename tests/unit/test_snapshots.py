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
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from app.chats.snapshots import snapshot_once
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat, ChatAvatar, ChatMemberSnapshot
from sqlalchemy import select, update

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


def _public(chat_id: int, username: str) -> Chat:
    return Chat(id=chat_id, title="A", resource_status=Chat.STATUS_EXTERNAL, public_link=f"https://t.me/{username}")


def _not_a_member(by_name: dict[str, tuple[int, int]]):
    """A bot that is in no chat: every id refused, each public name answered with its chat's id and size."""
    bot = _bot()

    async def _get_chat(chat_id):
        if isinstance(chat_id, int):
            raise _refused()
        found = MagicMock()
        found.id, found.type, found.title, found.photo = by_name[chat_id][0], "supergroup", "A", None
        found.username = chat_id.removeprefix("@")
        return found

    async def _count(chat_id):
        if isinstance(chat_id, int):
            raise _refused()
        return by_name[chat_id][1]

    bot.get_chat = AsyncMock(side_effect=_get_chat)
    bot.get_chat_member_count = AsyncMock(side_effect=_count)
    return bot


async def _seed(session_maker, *chats: Chat) -> None:
    async with session_maker() as session:
        for chat in chats:
            session.add(chat)
        await session.commit()


async def _snapshots(session_maker) -> list[tuple[int, int]]:
    async with session_maker() as session:
        rows = (await session.execute(select(ChatMemberSnapshot).order_by(ChatMemberSnapshot.chat_id))).scalars().all()
    return [(row.chat_id, row.member_count) for row in rows]


def _guessed() -> Chat:
    """A row the migration gave to the admins for want of a link."""
    chat = Chat(id=-100, title="A", join_mode=Chat.JOIN_ADMINS)
    chat.join_mode_guessed = True
    return chat


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
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=settings.chat_state.recheck_after_hours + 1)
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
        await _seed(db_session_maker, _guessed())

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=False, username=username))

        settled_chat = await _chat(db_session_maker, -100)
        assert settled_chat.join_mode == settled
        assert settled_chat.join_mode_guessed is False

    async def test_admins_somebody_chose_are_not_resettled(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A new chat or an upgraded one is never asked yet either; its admins are a choice, not a guess."""
        await _seed(db_session_maker, Chat(id=-100, title="A", join_mode=Chat.JOIN_ADMINS))

        await snapshot_once(session_maker=db_session_maker, bot=_bot(join_by_request=False))

        assert (await _chat(db_session_maker, -100)).join_mode == Chat.JOIN_ADMINS

    async def test_a_mode_set_while_the_chat_is_asked_is_kept(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The first run after the deploy asks every chat, a second apiece, while operators work."""
        await _seed(db_session_maker, _guessed())
        bot = _bot(join_by_request=False)
        answer = bot.get_chat.side_effect

        async def _get_chat(chat_id: int):
            async with db_session_maker() as session:
                await session.execute(update(Chat).where(Chat.id == -100).values(join_mode=Chat.JOIN_CAPTCHA))
                await session.commit()
            return await answer(chat_id)

        bot.get_chat.side_effect = _get_chat

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -100)).join_mode == Chat.JOIN_CAPTCHA

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
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=settings.chat_state.recheck_after_hours + 1)
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
        chat.last_synced_at = utc_now() - datetime.timedelta(hours=settings.chat_state.recheck_after_hours + 1)
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

    @pytest.mark.parametrize(("retry_after", "waits"), [(60, True), (61, False)])
    async def test_only_a_short_retry_after_is_waited_out(self, monkeypatch, retry_after: int, waits: bool) -> None:
        from aiogram.exceptions import TelegramRetryAfter
        from app.chats import metadata

        waited: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            waited.append(seconds)

        monkeypatch.setattr(metadata.asyncio, "sleep", fake_sleep)
        flood = TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=retry_after)
        bot = AsyncMock()
        bot.get_chat_member_count = AsyncMock(side_effect=[flood, 120])

        count = await metadata.fetch_member_count(bot=bot, chat_id=-100)

        assert (count == 120) is waits
        assert waited == ([retry_after] if waits else [])

    async def test_a_long_retry_after_on_the_name_is_not_waited_out(self, monkeypatch) -> None:
        """The incident of 2026-10-22: the id is unknown, the name is under an 80-minute wait."""
        from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
        from app.chats import metadata

        waited: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            waited.append(seconds)

        monkeypatch.setattr(metadata.asyncio, "sleep", fake_sleep)
        bot = AsyncMock()
        bot.get_chat = AsyncMock(
            side_effect=[
                TelegramBadRequest(method=MagicMock(), message="chat not found"),
                TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=4837),
            ]
        )

        assert await metadata.fetch_metadata(bot=bot, chat_id=-100, username="jcu_chat") is None
        assert bot.get_chat.await_count == 2
        assert waited == []

    async def test_a_long_retry_after_on_the_id_does_not_try_the_name(self, monkeypatch) -> None:
        from aiogram.exceptions import TelegramRetryAfter
        from app.chats import metadata

        waited: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            waited.append(seconds)

        monkeypatch.setattr(metadata.asyncio, "sleep", fake_sleep)
        bot = AsyncMock()
        bot.get_chat = AsyncMock(side_effect=TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=4837))

        assert await metadata.fetch_metadata(bot=bot, chat_id=-100, username="jcu_chat") is None
        assert bot.get_chat.await_count == 1
        assert waited == []


class TestBotNotInChat:
    """A chat the bot is not in says "chat not found" every hour, and nothing else.

    On 2026-10-20 the moderator moved to a new bot, and two chats it was never
    added to filled the log with the same two warnings every tick.
    """

    async def test_the_first_refusal_marks_the_chat(self, db_session_maker: async_sessionmaker[AsyncSession]) -> None:
        await _seed(db_session_maker, Chat(id=-100, title="A"))
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(side_effect=_refused())

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -100)).bot_absent_at is not None
        # Nothing to ask getChat about either: it would say the same.
        bot.get_chat.assert_not_awaited()

    async def test_a_marked_chat_is_not_asked_again_the_same_day(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        absent = Chat(id=-100, title="A")
        absent.bot_absent_at = utc_now() - datetime.timedelta(hours=2)
        await _seed(db_session_maker, absent, Chat(id=-200, title="B"))
        bot = _bot(counts={-200: 80})

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert [call.args[0] for call in bot.get_chat_member_count.await_args_list] == [-200]
        assert await _snapshots(db_session_maker) == [(-200, 80)]

    async def test_a_day_later_it_is_asked_again_and_counted_once_the_bot_is_there(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Nobody tells the bot it was added to a chat that is not approved; asking is how it finds out."""
        absent = Chat(id=-100, title="A")
        absent.bot_absent_at = utc_now() - datetime.timedelta(hours=25)
        await _seed(db_session_maker, absent)

        await snapshot_once(session_maker=db_session_maker, bot=_bot(counts={-100: 50}))

        assert await _snapshots(db_session_maker) == [(-100, 50)]
        assert (await _chat(db_session_maker, -100)).bot_absent_at is None

    async def test_still_absent_a_day_later_moves_the_mark(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        before = utc_now() - datetime.timedelta(hours=25)
        absent = Chat(id=-100, title="A")
        absent.bot_absent_at = before
        await _seed(db_session_maker, absent)
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(side_effect=_refused())

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        marked = (await _chat(db_session_maker, -100)).bot_absent_at
        assert marked is not None
        assert marked > before

    async def test_any_other_refusal_does_not_mark_the_chat(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """A timeout or a flood says nothing about whether the bot is there."""
        await _seed(db_session_maker, Chat(id=-100, title="A"))
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="Bad Request: something else")
        )

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -100)).bot_absent_at is None

    async def test_a_public_chat_is_still_asked_by_its_name(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Telegram refuses the id to a bot that is not in the chat, and answers its public name."""
        chat = Chat(id=-100, title="A", resource_status=Chat.STATUS_EXTERNAL, public_link="https://t.me/cvut_fjfi")
        await _seed(db_session_maker, chat)
        bot = _bot_with_photo("big-1", "small-1", "uniq-1")
        by_name = bot.get_chat.side_effect

        async def _get_chat(chat_id):
            if isinstance(chat_id, int):
                raise _refused()
            return await by_name(chat_id)

        bot.get_chat = AsyncMock(side_effect=_get_chat)
        bot.get_chat_member_count = AsyncMock(side_effect=_refused())

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert bot.get_chat.await_args_list[-1].args == ("@cvut_fjfi",)
        assert (await _chat(db_session_maker, -100)).bot_absent_at is not None
        async with db_session_maker() as session:
            assert await session.get(ChatAvatar, -100) is not None

    async def test_a_public_chat_is_counted_by_its_name(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """On 2026-10-22 twenty-two listed chats the bot is not in had no count at all."""
        await _seed(db_session_maker, _public(-100, "cvut_fjfi"))
        bot = _not_a_member({"@cvut_fjfi": (-100, 276)})

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert await _snapshots(db_session_maker) == [(-100, 276)]
        assert (await _chat(db_session_maker, -100)).bot_absent_at is not None

    async def test_a_name_now_another_chats_is_not_counted(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The count by name names no chat, so the name is checked against the id first."""
        await _seed(db_session_maker, _public(-100, "cvut_fjfi"))
        bot = _not_a_member({"@cvut_fjfi": (-999, 5000)})

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert await _snapshots(db_session_maker) == []
        bot.get_chat_member_count.assert_awaited_once_with(-100)

    async def test_a_marked_public_chat_waits_out_the_day_too(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Lookups by name are what earned the bot an 80-minute wait, so they are as rare as the id."""
        chat = _public(-100, "cvut_fjfi")
        chat.bot_absent_at = utc_now() - datetime.timedelta(hours=2)
        await _seed(db_session_maker, chat)
        bot = _not_a_member({"@cvut_fjfi": (-100, 276)})

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        bot.get_chat.assert_not_awaited()
        bot.get_chat_member_count.assert_not_awaited()

    async def test_a_flood_wait_by_name_ends_lookups_by_name_for_the_tick(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed(db_session_maker, _public(-100, "cvut_fjfi"), _public(-200, "cvut_fel"))
        bot = _not_a_member({"@cvut_fel": (-200, 700)})
        bot.get_chat = AsyncMock(
            side_effect=TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=4800)
        )

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert bot.get_chat.await_count == 1
        assert await _snapshots(db_session_maker) == []
        assert (await _chat(db_session_maker, -200)).bot_absent_at is not None

    async def test_a_flood_wait_on_the_count_by_name_keeps_the_title(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        public = _public(-100, "cvut_fjfi")
        public.title = "Old"
        await _seed(db_session_maker, public, _public(-200, "cvut_fel"))
        bot = _not_a_member({"@cvut_fjfi": (-100, 900), "@cvut_fel": (-200, 700)})
        bot.get_chat_member_count = AsyncMock(
            side_effect=[
                _refused(),
                TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=4800),
                _refused(),
            ]
        )

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        stored = await _chat(db_session_maker, -100)
        assert stored.title == "A"
        assert stored.last_synced_at is not None
        assert await _snapshots(db_session_maker) == []
        # The second chat is not asked by name at all.
        assert bot.get_chat_member_count.await_count == 3
        assert bot.get_chat.await_count == 1

    async def test_a_timeout_on_the_recheck_keeps_the_mark(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Otherwise the next tick hears "chat not found" again and warns as if for the first time."""
        absent = Chat(id=-100, title="A")
        absent.bot_absent_at = utc_now() - datetime.timedelta(hours=25)
        await _seed(db_session_maker, absent)
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(side_effect=TelegramNetworkError(method=MagicMock(), message="timeout"))

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -100)).bot_absent_at is not None


class TestUpgradedToSupergroup:
    """A group that became a supergroup answers its old id with the new one, for good.

    On 2026-10-22 one such group logged the same warning every hour.
    """

    async def test_the_old_row_says_where_it_went_and_is_not_asked_again(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        from aiogram.exceptions import TelegramMigrateToChat

        await _seed(db_session_maker, Chat(id=-5319178881, title="Old"), Chat(id=-200, title="B"))
        bot = _bot()
        moved = TelegramMigrateToChat(method=MagicMock(), message="upgraded", migrate_to_chat_id=-1004394473356)

        def _count(chat_id: int) -> int:
            if chat_id == -5319178881:
                raise moved
            return 80

        bot.get_chat_member_count = AsyncMock(side_effect=_count)

        await snapshot_once(session_maker=db_session_maker, bot=bot)
        await snapshot_once(session_maker=db_session_maker, bot=bot)

        old = await _chat(db_session_maker, -5319178881)
        assert old.migrated_to_chat_id == -1004394473356
        # Kept, with its history, and asked once only.
        asked = [call.args[0] for call in bot.get_chat_member_count.await_args_list]
        assert asked.count(-5319178881) == 1
        assert asked.count(-200) == 2
        assert -5319178881 not in [call.args[0] for call in bot.get_chat.await_args_list]
        # The second run counts the supergroup it was followed to instead.
        assert await _snapshots(db_session_maker) == [(-1004394473356, 80), (-200, 80), (-200, 80)]

    async def test_a_listed_chat_is_followed_to_its_new_id(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """The upgrade's announcement may never have reached the bot; Telegram's answer is the same fact."""
        from aiogram.exceptions import TelegramMigrateToChat

        await _seed(
            db_session_maker,
            Chat(id=-5319178881, title="Old", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/old"),
        )
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(
            side_effect=TelegramMigrateToChat(method=MagicMock(), message="upgraded", migrate_to_chat_id=-1004394473356)
        )

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        old = await _chat(db_session_maker, -5319178881)
        new = await _chat(db_session_maker, -1004394473356)
        assert (old.resource_status, old.public_link, old.migrated_to_chat_id) == (
            Chat.STATUS_DISABLED,
            None,
            -1004394473356,
        )
        assert (new.resource_status, new.public_link) == (Chat.STATUS_APPROVED, "https://t.me/old")

    async def test_a_follow_that_failed_is_tried_again_next_run(
        self, db_session_maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mark is committed before the follow, so a failed follow must not leave the old row listed for good."""
        import app.chats.snapshots as snapshots
        from aiogram.exceptions import TelegramMigrateToChat

        await _seed(
            db_session_maker,
            Chat(id=-5319178881, title="Old", resource_status=Chat.STATUS_APPROVED, public_link="https://t.me/old"),
        )
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(
            side_effect=TelegramMigrateToChat(method=MagicMock(), message="upgraded", migrate_to_chat_id=-1004394473356)
        )
        monkeypatch.setattr(snapshots, "follow_upgrade", AsyncMock(side_effect=RuntimeError("database went away")))

        await snapshot_once(session_maker=db_session_maker, bot=bot)

        old = await _chat(db_session_maker, -5319178881)
        assert (old.resource_status, old.migrated_to_chat_id) == (Chat.STATUS_APPROVED, -1004394473356)

        monkeypatch.undo()
        bot.get_chat_member_count = AsyncMock(return_value=80)
        await snapshot_once(session_maker=db_session_maker, bot=bot)

        old = await _chat(db_session_maker, -5319178881)
        assert (old.resource_status, old.public_link) == (Chat.STATUS_DISABLED, None)
        assert (await _chat(db_session_maker, -1004394473356)).public_link == "https://t.me/old"
        # The old id was not asked about again; the new one is counted from the next run.
        bot.get_chat_member_count.assert_not_awaited()

    async def test_a_disabled_group_is_marked_and_left_alone(
        self, db_session_maker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Nothing to follow for a chat nobody listed, but it is still not asked about again."""
        from aiogram.exceptions import TelegramMigrateToChat

        await _seed(db_session_maker, Chat(id=-5319178881, title="Old", resource_status=Chat.STATUS_DISABLED))
        bot = _bot()
        bot.get_chat_member_count = AsyncMock(
            side_effect=TelegramMigrateToChat(method=MagicMock(), message="upgraded", migrate_to_chat_id=-1004394473356)
        )

        await snapshot_once(session_maker=db_session_maker, bot=bot)
        await snapshot_once(session_maker=db_session_maker, bot=bot)

        assert (await _chat(db_session_maker, -5319178881)).migrated_to_chat_id == -1004394473356
        bot.get_chat_member_count.assert_awaited_once_with(-5319178881)


async def test_the_daily_pass_keeps_the_rest_of_the_answer(db_session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Description and slow mode change without an update; the daily getChat is where they are learnt."""
    await _seed(db_session_maker, Chat(id=-100, title="A"))
    bot = _bot()
    answer = bot.get_chat.side_effect

    async def _get_chat(chat_id: int):
        chat = await answer(chat_id)
        chat.description, chat.slow_mode_delay = "Правила в закрепе", 60
        return chat

    bot.get_chat = AsyncMock(side_effect=_get_chat)

    await snapshot_once(session_maker=db_session_maker, bot=bot)

    stored = await _chat(db_session_maker, -100)
    assert (stored.description, stored.slow_mode_delay) == ("Правила в закрепе", 60)
