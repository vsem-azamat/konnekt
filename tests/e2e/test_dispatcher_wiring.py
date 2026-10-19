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
from aiogram.types import Chat, ChatMemberLeft, ChatMemberRestricted, ChatMemberUpdated, Message, Update, User
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
    # The handler routers are module singletons; another test may hold them.
    router._parent_router = None
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


async def test_a_blacklisted_person_writing_to_the_bot_is_not_banned_there(
    dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    """There is no chat to ban anybody from in a private conversation."""
    person = User(id=BLOCKED_ID, is_bot=False, first_name="Spammer")
    update = Update(
        update_id=3,
        message=Message(
            message_id=11,
            date=datetime.now(UTC),
            chat=Chat(id=BLOCKED_ID, type="private", first_name="Spammer"),
            from_user=person,
            text="hello",
        ),
    )

    await dispatcher.feed_update(bot, update)

    assert _bans(fake_tg) == []
