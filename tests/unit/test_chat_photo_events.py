"""A chat changing its photo is reflected at once, not at the next daily sync.

Telegram posts a service message when a photo is set or removed. Its own photo
sizes are the message's, not the chat's, so the handler asks `getChat` and takes
that as the answer, like the loop does.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.db.models import Chat, ChatAvatar
from app.presentation.telegram.handlers.events import chat_photo_changed

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010


class _Notice:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"id": CHAT_ID})()


def _bot(*, photo: bool = True) -> AsyncMock:
    bot = AsyncMock()
    chat = MagicMock(title="ČVUT FIT")
    chat.photo = (
        MagicMock(big_file_id="big-2", small_file_id="small-2", small_file_unique_id="uniq-2") if photo else None
    )
    bot.get_chat = AsyncMock(return_value=chat)
    bot.download = AsyncMock(return_value=io.BytesIO(b"\xff\xd8\xff" + b"x" * 16))
    return bot


async def _chat(session) -> None:
    session.add(Chat(id=CHAT_ID, title="ČVUT FIT", resource_status=Chat.STATUS_APPROVED))
    await session.commit()


async def test_a_new_photo_is_picked_up_on_the_notice(session) -> None:
    await _chat(session)

    await chat_photo_changed(_Notice(), _bot(), session)

    avatar = await session.get(ChatAvatar, CHAT_ID)
    assert avatar is not None
    assert avatar.unique_id == "uniq-2"


async def test_a_removed_photo_drops_the_picture(session) -> None:
    await _chat(session)
    session.add(ChatAvatar(chat_id=CHAT_ID, unique_id="uniq-1", content=b"\xff\xd8\xff"))
    await session.commit()

    await chat_photo_changed(_Notice(), _bot(photo=False), session)

    assert await session.get(ChatAvatar, CHAT_ID) is None


async def test_telegram_not_answering_changes_nothing_and_does_not_raise(session) -> None:
    await _chat(session)
    bot = _bot()
    bot.get_chat = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))

    await chat_photo_changed(_Notice(), bot, session)

    assert await session.get(ChatAvatar, CHAT_ID) is None


async def test_a_chat_we_do_not_know_is_ignored(session) -> None:
    bot = _bot()

    await chat_photo_changed(_Notice(), bot, session)

    bot.get_chat.assert_not_awaited()


def _service_message(**fields: object):
    from aiogram.types import Message

    return Message.model_validate({"message_id": 1, "date": 0, "chat": {"id": CHAT_ID, "type": "supergroup"}, **fields})


def _handler():
    from app.presentation.telegram.handlers.events import router

    return next(h for h in router.message.handlers if h.callback is chat_photo_changed)


@pytest.mark.parametrize(
    "fields",
    [
        {"new_chat_photo": [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]},
        {"delete_chat_photo": True},
    ],
    ids=["set", "deleted"],
)
async def test_it_listens_for_both_service_messages(fields: dict[str, object]) -> None:
    """Setting a photo and deleting it are two different service messages."""
    matched, _ = await _handler().check(_service_message(**fields))

    assert matched


async def test_an_ordinary_message_does_not_reach_it() -> None:
    matched, _ = await _handler().check(_service_message(text="hi"))

    assert not matched
