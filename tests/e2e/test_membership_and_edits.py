"""Joins that are joins, and edits that are seen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import (
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberRestricted,
    ChatMemberUpdated,
    Message,
    Update,
    User,
)
from app.db.models import Chat as DbChat
from app.db.models import Message as DbMessage
from app.db.models import SpamPing
from sqlalchemy import select, update

from tests.e2e.conftest import APPROVED_CHAT_ID

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

GROUP = Chat(id=APPROVED_CHAT_ID, type="supergroup", title="Approved")
PERSON = User(id=555000555, is_bot=False, first_name="Member")


def _restricted() -> ChatMemberRestricted:
    return ChatMemberRestricted(
        user=PERSON,
        is_member=True,
        until_date=datetime.fromtimestamp(0, UTC),
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_react_to_messages=False,
        can_edit_tag=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


def _transition(old, new) -> Update:
    return Update(
        update_id=1,
        chat_member=ChatMemberUpdated(
            chat=GROUP, from_user=PERSON, date=datetime.now(UTC), old_chat_member=old, new_chat_member=new
        ),
    )


@pytest.fixture
async def greeting(db_session_maker: async_sessionmaker[AsyncSession], production_dispatcher: Dispatcher) -> Dispatcher:
    async with db_session_maker() as session:
        await session.execute(
            update(DbChat)
            .where(DbChat.id == APPROVED_CHAT_ID)
            .values(welcome_message="добро пожаловать", is_welcome_enabled=True)
        )
        await session.commit()
    return production_dispatcher


def _greeted(fake_tg: FakeTelegramServer) -> bool:
    return any("добро пожаловать" in str(c.params.get("text")) for c in fake_tg.get_calls("sendMessage"))


async def test_a_member_who_joins_is_greeted(greeting: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer) -> None:
    await greeting.feed_update(bot, _transition(ChatMemberLeft(user=PERSON), ChatMemberMember(user=PERSON)))

    assert _greeted(fake_tg)


async def test_lifting_a_mute_is_not_a_join(greeting: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer) -> None:
    """restricted -> member is the same person, who has been here all along."""
    await greeting.feed_update(bot, _transition(_restricted(), ChatMemberMember(user=PERSON)))

    assert not _greeted(fake_tg)


async def test_an_edit_into_an_ad_is_seen_and_recorded(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Posting something harmless and editing the link in afterwards went unseen."""
    original = Message(message_id=77, date=datetime.now(UTC), chat=GROUP, from_user=PERSON, text="привет всем")
    await production_dispatcher.feed_update(bot, Update(update_id=2, message=original))

    edited = original.model_copy(
        update={"text": "привет всем, заходите t.me/cheap_diplomas", "edit_date": int(datetime.now(UTC).timestamp())}
    )
    await production_dispatcher.feed_update(bot, Update(update_id=3, edited_message=edited))

    async with db_session_maker() as session:
        stored = await session.scalar(select(DbMessage).where(DbMessage.message_id == 77))
        pings = (await session.scalars(select(SpamPing).where(SpamPing.message_id == 77))).all()
    assert stored is not None
    assert "t.me/cheap_diplomas" in (stored.message or "")
    assert len(pings) == 1
