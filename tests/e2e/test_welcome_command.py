"""`!welcome` sets the greeting a chat gives new members."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import Chat, Message, MessageEntity, Update, User
from app.db.models import Chat as DbChat

from tests.e2e.conftest import APPROVED_CHAT_ID

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

SUPER_ADMIN_ID = 123456789


def _welcome(text: str, entities: list[MessageEntity] | None = None) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=10,
            date=datetime.now(UTC),
            chat=Chat(id=APPROVED_CHAT_ID, type="supergroup", title="Approved"),
            from_user=User(id=SUPER_ADMIN_ID, is_bot=False, first_name="Admin"),
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=8), *(entities or [])],
        ),
    )


async def _stored(db_session_maker: async_sessionmaker[AsyncSession]) -> DbChat:
    async with db_session_maker() as session:
        chat = await session.get(DbChat, APPROVED_CHAT_ID)
    assert chat is not None
    return chat


async def test_the_greeting_is_stored_as_safe_html_and_switched_on(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Typed text was stored raw and sent as HTML, so one `<` broke every join."""
    text = "!welcome Привет, <студент>! Правила — в закрепе"
    bold = MessageEntity(type="bold", offset=9, length=6)

    await production_dispatcher.feed_update(bot, _welcome(text, [bold]))

    chat = await _stored(db_session_maker)
    assert chat.welcome_message == "<b>Привет</b>, &lt;студент&gt;! Правила — в закрепе"
    assert chat.is_welcome_enabled is True


async def test_an_empty_greeting_is_refused(
    production_dispatcher: Dispatcher,
    bot: Bot,
    fake_tg: FakeTelegramServer,
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await production_dispatcher.feed_update(bot, _welcome("!welcome"))

    chat = await _stored(db_session_maker)
    assert chat.welcome_message is None
    assert chat.is_welcome_enabled is False
    assert any("!welcome" in str(c.params.get("text")) for c in fake_tg.get_calls("sendMessage"))
