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


async def test_joining_restricted_is_still_a_join(greeting: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer) -> None:
    """A chat that restricts newcomers still has newcomers."""
    await greeting.feed_update(bot, _transition(ChatMemberLeft(user=PERSON), _restricted()))

    assert _greeted(fake_tg)


def _edit(original: Message, text: str, update_id: int) -> Update:
    edited = original.model_copy(update={"text": text, "edit_date": int(datetime.now(UTC).timestamp())})
    return Update(update_id=update_id, edited_message=edited)


async def test_editing_a_message_again_and_again_counts_its_ad_once(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Every typo fix added another ping, and the console's counts grew with them."""
    original = Message(message_id=78, date=datetime.now(UTC), chat=GROUP, from_user=PERSON, text="t.me/cheap_diplomas")
    await production_dispatcher.feed_update(bot, Update(update_id=10, message=original))
    for i, text in enumerate(["t.me/cheap_diplomas !", "t.me/cheap_diplomas !!", "t.me/cheap_diplomas !!!"]):
        await production_dispatcher.feed_update(bot, _edit(original, text, 11 + i))

    async with db_session_maker() as session:
        pings = (await session.scalars(select(SpamPing).where(SpamPing.message_id == 78))).all()
    assert len(pings) == 1


async def test_an_edit_never_raises_the_first_message_warning(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    spam = "Дешёвые дипломы любого вуза"
    async with db_session_maker() as session:
        session.add(
            DbMessage(chat_id=APPROVED_CHAT_ID, user_id=1, message_id=5, message=spam, message_info={}, spam=True)
        )
        await session.commit()
    original = Message(
        message_id=79,
        date=datetime.now(UTC),
        chat=GROUP,
        from_user=User(id=999111, is_bot=False, first_name="N"),
        text="привет",
    )
    await production_dispatcher.feed_update(
        bot, Update(update_id=20, edited_message=original.model_copy(update={"text": spam}))
    )

    assert not any("Похоже на спам" in str(c.params.get("text")) for c in fake_tg.get_calls("sendMessage"))


async def test_an_edit_in_an_unapproved_chat_is_recorded_and_nothing_more(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    other = Chat(id=-1008888000111, type="supergroup", title="Not ours")
    original = Message(message_id=80, date=datetime.now(UTC), chat=other, from_user=PERSON, text="hi")
    await production_dispatcher.feed_update(
        bot, Update(update_id=30, edited_message=original.model_copy(update={"text": "t.me/ad"}))
    )

    async with db_session_maker() as session:
        stored = await session.scalar(select(DbMessage).where(DbMessage.chat_id == other.id))
        pings = (await session.scalars(select(SpamPing).where(SpamPing.chat_id == other.id))).all()
    assert stored is not None
    assert pings == []
    assert fake_tg.get_calls("sendMessage") == []


async def test_an_ad_edited_out_is_no_longer_counted(
    production_dispatcher: Dispatcher, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]
) -> None:
    original = Message(message_id=81, date=datetime.now(UTC), chat=GROUP, from_user=PERSON, text="t.me/cheap_diplomas")
    await production_dispatcher.feed_update(bot, Update(update_id=40, message=original))
    await production_dispatcher.feed_update(bot, _edit(original, "извините, ошибся чатом", 41))

    async with db_session_maker() as session:
        pings = (await session.scalars(select(SpamPing).where(SpamPing.message_id == 81))).all()
    assert pings == []
