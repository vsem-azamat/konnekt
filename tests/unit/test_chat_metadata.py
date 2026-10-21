"""Asking about a chat by its public name must not adopt a different chat's answer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from app.chats.metadata import fetch_metadata

pytestmark = pytest.mark.asyncio

CHAT = -1001370017010


def _bot(by_name: MagicMock) -> AsyncMock:
    async def _get_chat(chat_id):
        if isinstance(chat_id, int):
            raise TelegramBadRequest(method=MagicMock(), message="chat not found")
        return by_name

    bot = AsyncMock()
    bot.get_chat = AsyncMock(side_effect=_get_chat)
    return bot


def _answer(*, id: int = CHAT, type: str = "supergroup") -> MagicMock:
    return MagicMock(id=id, type=type, title="Whoever", photo=None)


async def test_the_same_chat_under_its_name_is_accepted() -> None:
    assert await fetch_metadata(bot=_bot(_answer()), chat_id=CHAT, username="cvut_fit") is not None


@pytest.mark.parametrize(
    "answer",
    [_answer(id=-1009999), _answer(type="channel"), _answer(type="private")],
    ids=["another-chat", "a-channel", "a-person"],
)
async def test_another_chat_that_took_the_name_is_not_this_one(answer) -> None:
    assert await fetch_metadata(bot=_bot(answer), chat_id=CHAT, username="cvut_fit") is None
