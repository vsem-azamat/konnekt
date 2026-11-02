"""/chats: the chats somebody is looking for, from where they asked.

Azamat's rule (9737): in a university's chat its faculties, in a faculty's the
whole university, in private the way into the catalogue; in a group the
command and the answer go after a while, so the chat does not fill with lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Chat
from app.presentation.telegram.handlers import start as start_handlers

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

UNIVERSITY = -1001
FACULTY = -1002
SITE = "https://konnekt.example"
BOT_USERNAME = "konnekt_test_bot"


@pytest.fixture
def deleted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, int]]:
    """What was scheduled for deletion, and after how long; nothing is waited for."""
    scheduled: list[tuple[object, int]] = []
    monkeypatch.setattr(start_handlers.other, "sleep_and_delete", lambda m, s: scheduled.append((m, s)))
    return scheduled


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.me = AsyncMock(return_value=MagicMock(username=BOT_USERNAME))
    tg_bot.delete_message = AsyncMock()
    return tg_bot


def _message(chat_id: int, chat_type: str = "supergroup", answered: int = 500) -> MagicMock:
    message = MagicMock()
    message.chat.id = chat_id
    message.chat.type = chat_type
    message.answer = AsyncMock(return_value=MagicMock(name="answer", message_id=answered))
    return message


@pytest.fixture(autouse=True)
def _no_earlier_answers() -> None:
    start_handlers._chats_answers.clear()


async def _seed(session: AsyncSession) -> None:
    session.add(
        Chat(
            id=UNIVERSITY,
            title="ČVUT | ЧВУТ",
            resource_status=Chat.STATUS_APPROVED,
            institution_code="cvut",
            public_link="https://t.me/cvut_example",
        )
    )
    session.add(
        Chat(
            id=FACULTY,
            title="ČVUT FIT",
            parent_chat_id=UNIVERSITY,
            resource_status=Chat.STATUS_APPROVED,
            public_link="https://t.me/+fit",
        )
    )
    await session.commit()


def _answered(message: MagicMock) -> tuple[str, list]:
    call = message.answer.await_args
    markup = call.kwargs.get("reply_markup")
    return call.args[0], [b for row in markup.inline_keyboard for b in row] if markup else []


async def test_a_university_chat_is_answered_with_its_faculties(session: AsyncSession, bot, deleted) -> None:
    await _seed(session)
    message = _message(UNIVERSITY)

    await start_handlers.get_chats(message, bot, session)

    text, [button] = _answered(message)
    assert text.splitlines()[0] == "<b>Чаты факультетов ČVUT</b>"
    assert '<a href="https://t.me/+fit">ČVUT FIT</a>' in text
    assert "cvut_example" not in text
    assert button.url == f"https://t.me/{BOT_USERNAME}?startapp=uni-cvut"


async def test_a_faculty_chat_is_answered_with_the_whole_university(session: AsyncSession, bot, deleted) -> None:
    await _seed(session)
    message = _message(FACULTY)

    await start_handlers.get_chats(message, bot, session)

    text, _ = _answered(message)
    assert text.splitlines()[0] == "<b>Чаты ČVUT</b>"
    assert text.index("cvut_example") < text.index("ČVUT FIT")


async def test_a_chat_of_no_university_is_pointed_at_the_catalogue(session: AsyncSession, bot, deleted) -> None:
    session.add(Chat(id=-5, title="Strahov", resource_status=Chat.STATUS_APPROVED))
    await session.commit()
    message = _message(-5)

    await start_handlers.get_chats(message, bot, session)

    text, [button] = _answered(message)
    assert text == start_handlers.CHATS_IN_APP
    assert button.url == f"https://t.me/{BOT_USERNAME}?startapp=chats"


async def test_in_a_group_the_command_and_the_answer_both_go_later(session: AsyncSession, bot, deleted) -> None:
    await _seed(session)
    message = _message(UNIVERSITY)

    await start_handlers.get_chats(message, bot, session)

    assert deleted == [
        (message, start_handlers.CHATS_ANSWER_SECONDS),
        (message.answer.return_value, start_handlers.CHATS_ANSWER_SECONDS),
    ]


async def test_in_private_it_opens_the_catalogue_and_stays(
    session: AsyncSession, bot, deleted, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(start_handlers.settings.webapi, "public_url", SITE)
    message = _message(42, "private")

    await start_handlers.get_chats(message, bot, session)

    _, [button] = _answered(message)
    assert button.web_app.url == f"{SITE}/chats"
    assert deleted == []


async def test_a_new_answer_takes_the_place_of_the_one_before(session: AsyncSession, bot, deleted) -> None:
    """Ten people typing /chats leave one list, not ten."""
    await _seed(session)

    await start_handlers.get_chats(_message(UNIVERSITY, answered=501), bot, session)
    await start_handlers.get_chats(_message(UNIVERSITY, answered=502), bot, session)

    bot.delete_message.assert_awaited_once_with(UNIVERSITY, 501)


async def test_in_private_without_a_site_it_still_has_somewhere_to_go(
    session: AsyncSession, bot, deleted, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(start_handlers.settings.webapi, "public_url", "")
    message = _message(42, "private")

    await start_handlers.get_chats(message, bot, session)

    _, [button] = _answered(message)
    assert button.url == f"https://t.me/{BOT_USERNAME}?startapp=chats"


async def test_a_faculty_chat_lists_its_university_even_when_the_university_chat_is_unlisted(
    session: AsyncSession, bot, deleted
) -> None:
    await _seed(session)
    university = await session.get(Chat, UNIVERSITY)
    assert university is not None
    university.public_link = None
    await session.commit()
    message = _message(FACULTY)

    await start_handlers.get_chats(message, bot, session)

    text, [button] = _answered(message)
    assert text.splitlines()[0] == "<b>Чаты ČVUT</b>"
    assert "ČVUT FIT" in text
    assert button.url.endswith("startapp=uni-cvut")


async def test_a_faculty_chat_of_an_undecided_university_is_pointed_at_the_catalogue(
    session: AsyncSession, bot, deleted
) -> None:
    """Neither the university's link nor its Telegram title is ours to show until it is decided."""
    await _seed(session)
    university = await session.get(Chat, UNIVERSITY)
    assert university is not None
    university.resource_status = Chat.STATUS_DISCOVERED
    await session.commit()
    message = _message(FACULTY)

    await start_handlers.get_chats(message, bot, session)

    text, _ = _answered(message)
    assert text == start_handlers.CHATS_IN_APP
