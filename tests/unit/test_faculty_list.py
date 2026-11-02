"""The faculties' chats a university chat pins, kept by the bot.

What matters to the thousands who read a pinned message: it appears only where
it was approved, it says what the catalog says, and after the first silent pin
every change is an edit that notifies nobody, never a new pin.
"""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.chats import faculty_list
from app.chats.faculty_list import sync_once
from app.core.config import settings
from app.db.models import Chat, ChatBotRights, FacultyList
from sqlalchemy.ext.asyncio import AsyncSession as Session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

UNIVERSITY = -1001
POSTED = 77
NOW = datetime.datetime(2026, 11, 2, 10, 0)


@pytest.fixture(autouse=True)
def _named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.telegram, "faculty_list_chats", [UNIVERSITY])


def _bot(*, edit=None, pin=None) -> AsyncMock:
    bot = AsyncMock()
    bot.me = AsyncMock(return_value=MagicMock(username="konnekt_test_bot"))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=POSTED))
    bot.edit_message_text = AsyncMock(side_effect=edit)
    bot.pin_chat_message = AsyncMock(side_effect=pin)
    return bot


def _refused(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=message)


async def _university(session: AsyncSession, *, pin: bool = True, status: str = Chat.STATUS_APPROVED) -> None:
    session.add(
        Chat(id=UNIVERSITY, title="ČVUT | ЧВУТ", resource_status=status, institution_code="cvut", public_link=None)
    )
    session.add(
        ChatBotRights(
            chat_id=UNIVERSITY,
            status="administrator",
            rights={"can_pin_messages": pin},
            changed_at=NOW,
            known_at=NOW,
        )
    )
    await session.commit()


async def _faculty(session: AsyncSession, chat_id: int, title: str, **fields) -> None:
    fields.setdefault("public_link", f"https://t.me/+{-chat_id}")
    fields.setdefault("resource_status", Chat.STATUS_APPROVED)
    session.add(Chat(id=chat_id, title=title, parent_chat_id=UNIVERSITY, **fields))
    await session.commit()


async def _sync(session_maker: async_sessionmaker[AsyncSession], bot: AsyncMock) -> dict[str, int]:
    return await sync_once(session_maker=session_maker, bot=bot, pause_seconds=0)


async def test_the_list_names_the_university_and_links_every_chat() -> None:
    body = faculty_list.text(
        faculty_list.university_name("ČVUT | ЧВУТ"),
        [faculty_list.Faculty("ČVUT FEL", "https://t.me/+a"), faculty_list.Faculty("A & B", "https://t.me/+b")],
    )

    assert body.splitlines()[0] == "📌 <b>Чаты факультетов ČVUT</b>"
    assert '• <a href="https://t.me/+a">ČVUT FEL</a>' in body
    assert "A &amp; B" in body
    assert body.splitlines()[-1] == "Чаты других вузов и факультетов — тоже в Konnekt 👇"


async def test_a_list_too_long_for_telegram_counts_the_rest() -> None:
    """Telegram refuses a message over 4096 characters; the button leads to every chat."""
    many = [faculty_list.Faculty(f"Fakulta s dlouhým názvem číslo {i:03}", f"https://t.me/+f{i}") for i in range(200)]

    body = faculty_list.text("ČVUT", many)

    visible = len(re.sub(r"<[^>]+>", "", body).encode("utf-16-le")) // 2
    assert visible <= 4096
    assert re.search(r"…и ещё \d+ — в Konnekt", body)
    assert body.splitlines()[-1] == faculty_list.FOOTER


async def test_nothing_is_posted_in_a_chat_nobody_named(
    session_maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.telegram, "faculty_list_chats", [])
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()

    assert await _sync(session_maker, bot) == {}

    bot.send_message.assert_not_called()


async def test_the_first_list_is_posted_and_pinned_without_a_sound(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -3, "ČVUT FIT")
        await _faculty(session, -2, "ČVUT FEL")
    bot = _bot()

    assert await _sync(session_maker, bot) == {"posted": 1}

    sent = bot.send_message.call_args
    assert sent.kwargs["disable_notification"] is True
    assert sent.args[1].index("ČVUT FEL") < sent.args[1].index("ČVUT FIT")
    url = sent.kwargs["reply_markup"].inline_keyboard[0][0].url
    assert url == "https://t.me/konnekt_test_bot?startapp=uni-cvut"
    bot.pin_chat_message.assert_awaited_once_with(UNIVERSITY, POSTED, disable_notification=True)
    async with session_maker() as session:
        kept = await session.get(FacultyList, UNIVERSITY)
        assert kept is not None
        assert kept.message_id == POSTED


async def test_without_the_right_to_pin_nothing_is_posted(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """A list that cannot be pinned would scroll away as one more message in the chat."""
    async with session_maker() as session:
        await _university(session, pin=False)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()

    assert await _sync(session_maker, bot) == {"no_pin_right": 1}

    bot.send_message.assert_not_called()


async def test_only_the_chats_the_catalog_lists_are_in_it(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
        await _faculty(session, -3, "No link", public_link=None)
        await _faculty(session, -4, "Not decided", resource_status=Chat.STATUS_DISCOVERED)
    bot = _bot()

    await _sync(session_maker, bot)

    body = bot.send_message.call_args.args[1]
    assert "ČVUT FIT" in body
    assert "No link" not in body
    assert "Not decided" not in body


async def test_a_new_chat_is_an_edit_of_the_same_message(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()
    await _sync(session_maker, bot)
    async with session_maker() as session:
        await _faculty(session, -3, "ČVUT FEL")

    assert await _sync(session_maker, bot) == {"edited": 1}

    assert bot.send_message.await_count == 1
    assert bot.pin_chat_message.await_count == 1
    edited = bot.edit_message_text.call_args
    assert edited.kwargs["message_id"] == POSTED
    assert "ČVUT FEL" in edited.args[0]


async def test_an_unchanged_list_is_left_alone(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()
    await _sync(session_maker, bot)

    assert await _sync(session_maker, bot) == {"unchanged": 1}

    bot.edit_message_text.assert_not_called()


async def test_a_list_somebody_removed_is_not_posted_again(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot(edit=_refused("Bad Request: message to edit not found"))
    await _sync(session_maker, bot)
    async with session_maker() as session:
        await _faculty(session, -3, "ČVUT FEL")

    assert await _sync(session_maker, bot) == {"gone": 1}
    assert await _sync(session_maker, bot) == {"gone": 1}

    assert bot.send_message.await_count == 1
    assert bot.edit_message_text.await_count == 1


async def test_a_chat_taken_down_gets_nothing(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session, status=Chat.STATUS_EXTERNAL)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()

    assert await _sync(session_maker, bot) == {"not_approved": 1}

    bot.send_message.assert_not_called()


async def test_a_pin_that_failed_is_tried_again_not_posted_again(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot(pin=[_refused("Bad Request: not enough rights"), None])

    assert await _sync(session_maker, bot) == {"failed": 1}
    assert await _sync(session_maker, bot) == {"unchanged": 1}

    assert bot.send_message.await_count == 1
    assert bot.pin_chat_message.await_count == 2
    async with session_maker() as session:
        kept = await session.get(FacultyList, UNIVERSITY)
        assert kept is not None
        assert kept.pinned_at is not None


async def test_a_list_that_could_not_be_recorded_is_taken_back(
    session_maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unrecorded, it would be posted a second time on the next round."""
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()

    async def refuse(self) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(Session, "commit", refuse)

    assert await _sync(session_maker, bot) == {"failed": 1}

    bot.delete_message.assert_awaited_once_with(UNIVERSITY, POSTED)
    bot.pin_chat_message.assert_not_called()


async def test_an_edit_telegram_finds_unchanged_counts_as_unchanged(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot(edit=_refused("Bad Request: message is not modified"))
    await _sync(session_maker, bot)
    async with session_maker() as session:
        await _faculty(session, -3, "ČVUT FEL")

    assert await _sync(session_maker, bot) == {"unchanged": 1}
    assert await _sync(session_maker, bot) == {"unchanged": 1}

    assert bot.edit_message_text.await_count == 1


async def test_a_new_university_code_moves_the_button(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """The text stays the same, but the old button would open a section that is no longer there."""
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot()
    await _sync(session_maker, bot)
    async with session_maker() as session:
        chat = await session.get(Chat, UNIVERSITY)
        assert chat is not None
        chat.institution_code = "cvut2"
        await session.commit()

    assert await _sync(session_maker, bot) == {"edited": 1}

    url = bot.edit_message_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].url
    assert url.endswith("startapp=uni-cvut2")


async def test_a_list_removed_before_its_pin_is_left_alone(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await _university(session)
        await _faculty(session, -2, "ČVUT FIT")
    bot = _bot(pin=[_refused("Bad Request: not enough rights"), _refused("Bad Request: message to pin not found")])
    await _sync(session_maker, bot)

    assert await _sync(session_maker, bot) == {"gone": 1}
    assert await _sync(session_maker, bot) == {"gone": 1}

    assert bot.send_message.await_count == 1
    assert bot.pin_chat_message.await_count == 2
