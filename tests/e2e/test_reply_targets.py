"""Who a reply-based command acts on.

Every moderation command takes its target from the message it replies to, and
Telegram does not always put a person there: a message sent as a channel or by
an anonymous admin carries a shared stand-in, and a message in a forum topic
that replies to nothing still points at the topic's first message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import Chat, ForumTopicCreated, Message, MessageEntity, Update, User
from app.db.repositories import get_admin_repository

from tests.e2e.conftest import APPROVED_CHAT_ID

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

SUPER_ADMIN_ID = 123456789  # ADMIN_SUPER_ADMINS in the test environment
MODERATOR_ID = 444000444
OTHER_MODERATOR_ID = 444000445
MEMBER_ID = 555000777
CHANNEL = Chat(id=-1007777777777, type="channel", title="Spam channel")
GROUP = Chat(id=APPROVED_CHAT_ID, type="supergroup", title="Approved", is_forum=True)
_ids = iter(range(1000, 100000))


def _person(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"U{uid}")


def _message(text: str = "hello", *, sender: int = MEMBER_ID, **fields) -> Message:
    return Message(
        message_id=next(_ids), date=datetime.now(UTC), chat=GROUP, from_user=_person(sender), text=text, **fields
    )


def _command(text: str, reply: Message | None, *, sender: int = SUPER_ADMIN_ID, **fields) -> Update:
    name = text.split()[0]
    message = _message(
        text,
        sender=sender,
        reply_to_message=reply,
        entities=[MessageEntity(type="bot_command", offset=0, length=len(name))],
        **fields,
    )
    return Update(update_id=next(_ids), message=message)


def _calls(fake_tg: FakeTelegramServer, method: str) -> list[dict]:
    return [c.params for c in fake_tg.get_calls(method)]


def _answers(fake_tg: FakeTelegramServer) -> str:
    return "\n".join(str(c["text"]) for c in _calls(fake_tg, "sendMessage"))


async def test_a_channel_post_is_banned_as_the_channel(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """The stand-in user is shared by every channel post; the channel is the author."""
    post = _message("buy now", sender=136817688, sender_chat=CHANNEL)

    await production_dispatcher.feed_update(bot, _command("!ban", post))

    assert [int(c["sender_chat_id"]) for c in _calls(fake_tg, "banChatSenderChat")] == [CHANNEL.id]
    assert _calls(fake_tg, "banChatMember") == []


async def test_an_anonymous_admin_is_not_acted_on(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    anonymous = _message("hi", sender=1087968824, sender_chat=GROUP)

    await production_dispatcher.feed_update(bot, _command("!ban", anonymous))

    assert _calls(fake_tg, "banChatMember") == []
    assert _calls(fake_tg, "banChatSenderChat") == []
    assert "от имени" in _answers(fake_tg)


@pytest.mark.parametrize("command", ["!mute 5m", "!kick", "/banall"])
async def test_commands_meant_for_a_person_refuse_a_channel_post(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, command: str
) -> None:
    """Muting or blacklisting the stand-in would hit every channel post everywhere."""
    post = _message("buy now", sender=136817688, sender_chat=CHANNEL)

    await production_dispatcher.feed_update(bot, _command(command, post))

    assert _calls(fake_tg, "restrictChatMember") == []
    assert _calls(fake_tg, "banChatMember") == []
    assert "от имени" in _answers(fake_tg)


async def test_an_anonymous_admin_is_not_made_a_moderator(
    production_dispatcher: Dispatcher,
    bot: Bot,
    fake_tg: FakeTelegramServer,
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Granting the stand-in would trust every anonymous admin in the chat."""
    anonymous = _message("hi", sender=1087968824, sender_chat=GROUP)

    await production_dispatcher.feed_update(bot, _command("!admin", anonymous))

    async with db_session_maker() as session:
        assert not await get_admin_repository(session).is_admin_in(1087968824, APPROVED_CHAT_ID)


async def test_a_command_in_a_topic_without_a_reply_has_no_target(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """Telegram points it at the topic's first message, whose author is the topic's creator."""
    topic_root = _message("", sender=MEMBER_ID, forum_topic_created=ForumTopicCreated(name="Q&A", icon_color=0))
    update = _command("!mute 1h", topic_root, message_thread_id=topic_root.message_id, is_topic_message=True)

    await production_dispatcher.feed_update(bot, update)

    assert _calls(fake_tg, "restrictChatMember") == []
    assert "ответом" in _answers(fake_tg)


async def test_a_super_admin_cannot_be_banned_from_a_chat(
    production_dispatcher: Dispatcher,
    bot: Bot,
    fake_tg: FakeTelegramServer,
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_maker() as session:
        await get_admin_repository(session).grant(MODERATOR_ID, APPROVED_CHAT_ID)

    await production_dispatcher.feed_update(bot, _command("!ban", _message(sender=SUPER_ADMIN_ID), sender=MODERATOR_ID))

    assert _calls(fake_tg, "banChatMember") == []


async def test_a_moderator_cannot_mute_another_moderator_of_the_chat(
    production_dispatcher: Dispatcher,
    bot: Bot,
    fake_tg: FakeTelegramServer,
    db_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_maker() as session:
        await get_admin_repository(session).grant(MODERATOR_ID, APPROVED_CHAT_ID)
        await get_admin_repository(session).grant(OTHER_MODERATOR_ID, APPROVED_CHAT_ID)

    await production_dispatcher.feed_update(
        bot, _command("!mute 5m", _message(sender=OTHER_MODERATOR_ID), sender=MODERATOR_ID)
    )

    assert _calls(fake_tg, "restrictChatMember") == []


async def test_unban_never_removes_someone_still_in_the_chat(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """Without only_if_banned, Telegram's unban kicks a current member."""
    await production_dispatcher.feed_update(bot, _command("!unban", _message(sender=MEMBER_ID)))

    (call,) = _calls(fake_tg, "unbanChatMember")
    assert str(call["only_if_banned"]).lower() == "true"
