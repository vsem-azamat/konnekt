"""The production dispatcher records the bot's own membership, in chats nobody has approved yet too."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import Update
from app.db.models import Chat, ChatBotRights

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.e2e

NEW_CHAT_ID = -1009876543210


async def test_being_added_to_a_new_chat_is_recorded_before_the_approval_gate(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    me = {"id": bot.id, "is_bot": True, "first_name": "Konnekt"}
    update = Update.model_validate(
        {
            "update_id": 1,
            "my_chat_member": {
                "chat": {"id": NEW_CHAT_ID, "type": "supergroup", "title": "New"},
                "from": {"id": 7, "is_bot": False, "first_name": "Owner"},
                "date": int(datetime.now(UTC).timestamp()),
                "old_chat_member": {"status": "left", "user": me},
                "new_chat_member": {"status": "member", "user": me},
            },
        }
    )

    await production_dispatcher.feed_update(bot, update)

    async with db_session_maker() as session:
        chat = await session.get(Chat, NEW_CHAT_ID)
        rights = await session.get(ChatBotRights, NEW_CHAT_ID)
    assert chat is not None
    assert chat.resource_status == Chat.STATUS_DISCOVERED
    assert rights is not None
    assert rights.status == "member"
