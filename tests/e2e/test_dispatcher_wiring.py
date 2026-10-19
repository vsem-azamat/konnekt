"""The production dispatcher, fed real updates against a fake Telegram.

Middlewares tested one by one pass while the wiring around them is wrong: the
blacklist check was correct for a year and never ran on a plain message,
because it sat behind filters that only commands match.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import (
    Chat,
    ChatMemberLeft,
    ChatMemberRestricted,
    ChatMemberUpdated,
    Message,
    MessageEntity,
    Update,
    User,
)
from app.db.models import Chat as DbChat
from app.db.models import User as DbUser
from app.presentation.telegram.bot import build_dispatcher
from app.presentation.telegram.handlers import router
from app.presentation.telegram.middlewares.black_list import invalidate_blacklist_cache

if TYPE_CHECKING:
    from aiogram import Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

CHAT_ID = -1001234567890
BLOCKED_ID = 555000555
GROUP = Chat(id=CHAT_ID, type="supergroup", title="Approved")


@pytest_asyncio.fixture()
async def bot(fake_tg: FakeTelegramServer):
    api = TelegramAPIServer(
        base=f"{fake_tg.base_url}/bot{{token}}/{{method}}",
        file=f"{fake_tg.base_url}/file/bot{{token}}/{{path}}",
        is_local=True,
    )
    b = Bot(
        token="123456:ABC-DEF1234567890",
        default=DefaultBotProperties(parse_mode="HTML"),
        session=AiohttpSession(api=api),
    )
    yield b
    await b.session.close()


@pytest_asyncio.fixture()
async def dispatcher(bot: Bot, db_session_maker: async_sessionmaker[AsyncSession]):
    # The handler routers are module singletons, and another test re-parents
    # them under a router of its own; put them back under ours.
    router._parent_router = None
    for sub in router.sub_routers:
        sub._parent_router = router
    invalidate_blacklist_cache()
    async with db_session_maker() as session:
        session.add(DbChat(id=CHAT_ID, title="Approved", resource_status=DbChat.STATUS_APPROVED))
        session.add(DbUser(id=BLOCKED_ID, first_name="Spammer", blocked=True))
        await session.commit()
    yield build_dispatcher(bot, db_session_maker)
    router._parent_router = None
    invalidate_blacklist_cache()


def _bans(fake_tg: FakeTelegramServer) -> list[int]:
    return [int(c.params["user_id"]) for c in fake_tg.get_calls("banChatMember")]


async def test_a_blacklisted_member_writing_plain_text_is_banned(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    update = Update(
        update_id=1,
        message=Message(
            message_id=10,
            date=datetime.now(UTC),
            chat=GROUP,
            from_user=User(id=BLOCKED_ID, is_bot=False, first_name="Spammer"),
            text="buy crypto at t.me/scam",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == [BLOCKED_ID]
    assert fake_tg.get_calls("deleteMessage")


async def test_a_blacklisted_person_rejoining_restricted_is_banned(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """No handler listens for left → restricted, so only the door can catch it."""
    person = User(id=BLOCKED_ID, is_bot=False, first_name="Spammer")
    update = Update(
        update_id=2,
        chat_member=ChatMemberUpdated(
            chat=GROUP,
            from_user=person,
            date=datetime.now(UTC),
            old_chat_member=ChatMemberLeft(user=person),
            new_chat_member=ChatMemberRestricted(
                user=person,
                is_member=True,
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
                until_date=datetime.fromtimestamp(0, UTC),
            ),
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == [BLOCKED_ID]


async def test_a_blacklisted_person_writing_to_the_bot_is_not_banned_or_answered(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """There is no chat to ban from in a private conversation, and no service either."""
    person = User(id=BLOCKED_ID, is_bot=False, first_name="Spammer")
    update = Update(
        update_id=3,
        message=Message(
            message_id=11,
            date=datetime.now(UTC),
            chat=Chat(id=BLOCKED_ID, type="private", first_name="Spammer"),
            from_user=person,
            text="/start",
            entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == []
    assert fake_tg.get_calls("sendMessage") == []


async def test_a_blacklisted_member_of_an_unapproved_chat_is_left_alone(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """The approval gate runs first: no public action where the owner has not agreed."""
    update = Update(
        update_id=4,
        message=Message(
            message_id=12,
            date=datetime.now(UTC),
            chat=Chat(id=-1009999999999, type="supergroup", title="Not ours"),
            from_user=User(id=BLOCKED_ID, is_bot=False, first_name="Spammer"),
            text="hello",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == []


async def test_a_message_sent_as_a_channel_is_not_judged_by_its_placeholder_sender(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    """Telegram puts a stand-in user on messages sent as a channel or anonymously.

    Blacklisting that stand-in by replying to one such message would otherwise
    silence every channel post and anonymous admin in every approved chat.
    """
    stand_in = 136817688
    async with db_session_maker() as session:
        session.add(DbUser(id=stand_in, first_name="Channel", blocked=True))
        await session.commit()
    invalidate_blacklist_cache()
    update = Update(
        update_id=5,
        message=Message(
            message_id=13,
            date=datetime.now(UTC),
            chat=GROUP,
            from_user=User(id=stand_in, is_bot=True, first_name="Channel"),
            sender_chat=Chat(id=-1001111111111, type="channel", title="Some channel"),
            text="a post",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == []
    assert fake_tg.get_calls("deleteMessage") == []


async def test_a_failed_ban_still_removes_the_message(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    fake_tg.set_response(
        "banChatMember", {"ok": False, "error_code": 400, "description": "Bad Request: not enough rights"}
    )
    update = Update(
        update_id=6,
        message=Message(
            message_id=14,
            date=datetime.now(UTC),
            chat=GROUP,
            from_user=User(id=BLOCKED_ID, is_bot=False, first_name="Spammer"),
            text="spam",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert fake_tg.get_calls("deleteMessage")
