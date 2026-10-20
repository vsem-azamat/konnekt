"""The production dispatcher records whoever uses the bot in private, and nobody else."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import Chat, Message, MessageEntity, Update, User
from app.core.enums import Touchpoint
from app.db.models import AudienceMember, AudienceTouch
from sqlalchemy import select

from tests.e2e.conftest import APPROVED_CHAT_ID

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.e2e

PERSON = User(id=60606, is_bot=False, first_name="Jan", username="jans", language_code="cs")


def _message(chat: Chat, text: str) -> Message:
    entities = [MessageEntity(type="bot_command", offset=0, length=6)] if text.startswith("/start") else None
    return Message(message_id=7, date=datetime.now(UTC), chat=chat, from_user=PERSON, text=text, entities=entities)


async def test_start_in_private_joins_the_audience_with_its_payload(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    private = Chat(id=PERSON.id, type="private", first_name="Jan")

    await production_dispatcher.feed_update(bot, Update(update_id=1, message=_message(private, "/start vut")))

    async with db_session_maker() as session:
        member = await session.get(AudienceMember, PERSON.id)
        touches = [t.touchpoint for t in await session.scalars(select(AudienceTouch))]
    assert member is not None
    assert (member.source, member.language_code) == ("vut", "cs")
    assert touches == [Touchpoint.MAIN_BOT]


async def test_writing_in_a_moderated_group_is_not_using_the_bot(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    group = Chat(id=APPROVED_CHAT_ID, type="supergroup", title="Approved")

    await production_dispatcher.feed_update(bot, Update(update_id=1, message=_message(group, "hello everyone")))

    async with db_session_maker() as session:
        assert await session.get(AudienceMember, PERSON.id) is None
