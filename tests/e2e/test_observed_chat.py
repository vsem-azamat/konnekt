"""A chat the bot only observes: present, recording, and silent.

The case it exists for is a chat whose owner runs their own bot. Ours is added
for the history and the member count, and anything it says or does there
competes with the bot actually in charge. So a moderator's command, Telegram's
"joined" notice and a stranger's first message, one that repeats known spam,
all go through the production dispatcher, and the only trace any of them may leave is the recorded message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import Chat, Message, MessageEntity, Update, User
from app.db.models import Chat as DbChat
from app.db.models import Message as DbMessage
from sqlalchemy import select

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

SUPER_ADMIN_ID = 123456789  # matches conftest env ADMIN_SUPER_ADMINS
OBSERVED = Chat(id=-1007777777777, type="supergroup", title="Someone else's bot runs this")
STRANGER = User(id=333, is_bot=False, first_name="Stranger")
SPEAKING = ("sendMessage", "deleteMessage", "deleteMessages", "banChatMember", "restrictChatMember")


def _message(message_id: int, sender: User, **fields) -> Message:
    return Message(message_id=message_id, date=datetime.now(UTC), chat=OBSERVED, from_user=sender, **fields)


async def test_an_observed_chat_is_recorded_and_never_answered(
    bot: Bot, db_session_maker: async_sessionmaker[AsyncSession], fake_tg: FakeTelegramServer
) -> None:
    from app.presentation.telegram.bot import build_dispatcher
    from app.presentation.telegram.handlers import router

    router._parent_router = None
    for sub in router.sub_routers:
        sub._parent_router = router
    dp = build_dispatcher(bot, db_session_maker)
    spam_text = "Дешёвые дипломы любого вуза, пишите в личку"
    async with db_session_maker() as session:
        session.add(DbChat(id=OBSERVED.id, title=OBSERVED.title, resource_status=DbChat.STATUS_OBSERVED))
        # Known spam, so a stranger's first message repeating it would be
        # flagged aloud in a chat we moderate.
        session.add(
            DbMessage(
                chat_id=OBSERVED.id, user_id=999000999, message_id=900, message=spam_text, message_info={}, spam=True
            )
        )
        await session.commit()

    written = _message(1, STRANGER, text=spam_text)
    admin = User(id=SUPER_ADMIN_ID, is_bot=False, first_name="Admin")
    updates = [
        written,
        _message(
            2,
            admin,
            text="!ban",
            entities=[MessageEntity(type="bot_command", offset=0, length=4)],
            reply_to_message=written,
        ),
        _message(3, STRANGER, new_chat_members=[STRANGER]),
    ]
    for update_id, message in enumerate(updates, start=1):
        await dp.feed_update(bot, Update(update_id=update_id, message=message))
    router._parent_router = None

    assert [call.method for call in fake_tg.get_calls() if call.method in SPEAKING] == []
    async with db_session_maker() as session:
        stored = await session.scalar(
            select(DbMessage).where(DbMessage.chat_id == OBSERVED.id, DbMessage.message_id == 1)
        )
        assert stored is not None
        chat = await session.get(DbChat, OBSERVED.id)
        assert chat is not None
        assert chat.resource_status == DbChat.STATUS_OBSERVED
