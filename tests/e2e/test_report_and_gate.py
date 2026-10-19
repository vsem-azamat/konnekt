"""`/report` and the approval gate, driven through a fake Telegram.

The dispatcher is fed real `Update` objects against `FakeTelegramServer` and an
in-memory SQLite, so what is pinned here is the routing — which handler a
command actually reaches once every middleware has had its say. That is exactly
the thing unit tests cannot see, and exactly where `/report` and `!report` drifted
into two different implementations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Chat,
    Message,
    MessageEntity,
    Update,
    User,
)
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from app.db.models import Chat as DbChat
from app.db.models import Message as DbMessage
from app.db.models import SpamPing
from app.moderation import spam_service
from app.presentation.telegram.middlewares import (
    ApprovedChatGateMiddleware,
    DependenciesMiddleware,
    HistoryMiddleware,
    ManagedChatsMiddleware,
)
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer


def _build_router() -> Any:
    """Build a fresh router tree for testing (avoids 'already attached' errors)."""
    from aiogram import Router
    from app.presentation.telegram.handlers import (
        admin,
        events,
        groups,
        moderation,
        service,
        start,
    )
    from app.presentation.telegram.middlewares import chat_type as chat_type_mw

    # Re-create sub-routers to avoid reuse issues
    r = Router()

    # The sub-routers are module-level singletons, so a fresh parent per test is
    # not enough — they have to be detached from the previous one first.
    sub_routers = [
        moderation.moderation_router,
        start.router,
        admin.admin_router,
        groups.groups_router,
        service.router,
        events.router,
    ]
    for sr in sub_routers:
        sr._parent_router = None  # force detach

    # Re-wire middlewares on sub-routers (same as handlers/__init__.py)
    groups.groups_router.message.middleware(chat_type_mw.ChatTypeMiddleware(["group", "supergroup"]))

    r.include_router(moderation.moderation_router)
    r.include_router(start.router)
    r.include_router(admin.admin_router)
    r.include_router(groups.groups_router)
    r.include_router(service.router)
    r.include_router(events.router)
    return r


# ---- Test users / chats ----

SUPER_ADMIN_ID = 123456789  # matches conftest env ADMIN_SUPER_ADMINS
REPORTER_ID = 111111111
TARGET_USER_ID = 222222222
CHAT_ID = -1001234567890


def _make_user(uid: int, first_name: str = "User", username: str | None = None) -> dict[str, Any]:
    return {
        "id": uid,
        "is_bot": False,
        "first_name": first_name,
        "username": username,
    }


def _make_chat(cid: int = CHAT_ID) -> dict[str, Any]:
    return {
        "id": cid,
        "type": "supergroup",
        "title": "Test Chat",
    }


def _make_message(
    text: str,
    from_user_id: int = REPORTER_ID,
    message_id: int = 42,
    chat_id: int = CHAT_ID,
    entities: list[dict[str, Any]] | None = None,
    reply_to_message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "from": _make_user(from_user_id, username=f"user_{from_user_id}"),
        "chat": _make_chat(chat_id),
        "date": int(datetime.now(UTC).timestamp()),
        "text": text,
        "entities": entities or [],
        "reply_to_message": reply_to_message,
    }


def _make_command_message(
    command: str,
    from_user_id: int = REPORTER_ID,
    reply_to_message: dict[str, Any] | None = None,
    message_id: int = 50,
) -> dict[str, Any]:
    text = f"/{command}"
    entities = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    return _make_message(
        text=text,
        from_user_id=from_user_id,
        message_id=message_id,
        entities=entities,
        reply_to_message=reply_to_message,
    )


def _make_target_message(text: str = "Buy cheap diploma!!! Contact @scammer") -> dict[str, Any]:
    """The message being reported."""
    return _make_message(
        text=text,
        from_user_id=TARGET_USER_ID,
        message_id=30,
    )


def _make_callback_query(
    data: str,
    from_user_id: int = SUPER_ADMIN_ID,
    message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "cb_123",
        "from": _make_user(from_user_id, first_name="Admin", username="super_admin"),
        "chat_instance": "12345",
        "data": data,
        "message": message or _make_message("Escalation text", from_user_id=5145935834, message_id=999),
    }


# ---- Fixtures ----


@pytest_asyncio.fixture()
async def db_session(db_session_maker):
    async with db_session_maker() as session:
        yield session


@pytest_asyncio.fixture()
async def fake_tg(fake_tg: FakeTelegramServer):
    """Wrap shared fake_tg with chat admin setup for moderation tests."""
    fake_tg.set_chat_admins(CHAT_ID, [SUPER_ADMIN_ID])
    yield fake_tg


@pytest_asyncio.fixture()
async def bot(fake_tg: FakeTelegramServer):
    """Bot connected to fake Telegram server."""
    from aiogram.client.telegram import TelegramAPIServer

    api_server = TelegramAPIServer(
        base=f"{fake_tg.base_url}/bot{{token}}/{{method}}",
        file=f"{fake_tg.base_url}/file/bot{{token}}/{{path}}",
        is_local=True,
    )
    session = AiohttpSession(api=api_server)
    b = Bot(
        token="123456:ABC-DEF1234567890",
        default=DefaultBotProperties(parse_mode="HTML"),
        session=session,
    )
    yield b
    await b.session.close()


@pytest_asyncio.fixture()
async def dispatcher(
    bot: Bot,
    db_session_maker: async_sessionmaker[AsyncSession],
    fake_tg: FakeTelegramServer,
):
    """Fully wired dispatcher with middlewares and handlers."""
    dp = Dispatcher()

    dp.update.middleware(DependenciesMiddleware(session_pool=db_session_maker, bot=bot))
    dp.update.middleware(ManagedChatsMiddleware())
    dp.update.middleware(HistoryMiddleware())
    dp.update.middleware(ApprovedChatGateMiddleware())
    dp.callback_query.middleware(CallbackAnswerMiddleware())
    dp.include_router(_build_router())

    async with db_session_maker() as session:
        await session.merge(DbChat(id=CHAT_ID, title="Test Chat", resource_status=DbChat.STATUS_APPROVED))
        await session.commit()

    yield dp


# ---- Tests ----


@pytest.mark.e2e
class TestReportCommand:
    """`/report` — the one command an ordinary member has."""

    async def test_report_without_reply_shows_hint(self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer):
        """Sending /report without replying to a message should show a hint."""
        update = Update(
            update_id=1,
            message=Message(
                message_id=50,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter"),
                text="/report",
                entities=[MessageEntity(type="bot_command", offset=0, length=7)],
            ),
        )

        await dispatcher.feed_update(bot, update)

        send_calls = fake_tg.get_calls("sendMessage")
        assert len(send_calls) >= 1
        # Should contain hint about replying
        sent_text = send_calls[0].params.get("text", "")
        assert "Ответьте" in sent_text or "reply" in sent_text.lower()

    async def test_report_forwards_to_admin(self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer):
        """Sending /report as reply should forward a summary to admin chat."""
        target_msg = Message(
            message_id=30,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
            from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target", username="target_user"),
            text="Buy cheap diploma!!!",
        )

        update = Update(
            update_id=2,
            message=Message(
                message_id=50,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter", username="reporter_user"),
                text="/report",
                entities=[MessageEntity(type="bot_command", offset=0, length=7)],
                reply_to_message=target_msg,
            ),
        )

        await dispatcher.feed_update(bot, update)

        # Should have sent summary to admin and acknowledgment in chat
        send_calls = fake_tg.get_calls("sendMessage")
        # At least: admin summary + chat acknowledgment
        assert len(send_calls) >= 2

        # Admin summary should contain report details
        admin_msg = next(
            (c for c in send_calls if str(c.params.get("chat_id", "")) == str(SUPER_ADMIN_ID)),
            None,
        )
        assert admin_msg is not None
        admin_text = admin_msg.params.get("text", "")
        assert "Жалоба" in admin_text
        assert "Target" in admin_text or str(TARGET_USER_ID) in admin_text
        assert "t.me/" in admin_text  # chat and message links present
        assert "Перейти к сообщению" in admin_text

        # Chat acknowledgment
        chat_msg = next(
            (c for c in send_calls if str(c.params.get("chat_id", "")) == str(CHAT_ID)),
            None,
        )
        assert chat_msg is not None
        assert "Жалоба отправлена" in chat_msg.params.get("text", "")

    async def test_both_prefixes_reach_the_same_handler(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
    ):
        """`!report` used to be a second implementation in another file.

        Feeding the bang form and comparing the summary against the slash form
        is the only way to catch them drifting apart again — the two handlers
        each had passing unit tests the whole time they disagreed.
        """
        target_msg = Message(
            message_id=31,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
            from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
            text="Buy cheap diploma!!!",
        )

        update = Update(
            update_id=3,
            message=Message(
                message_id=51,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter"),
                text="!report",
                entities=[MessageEntity(type="bot_command", offset=0, length=7)],
                reply_to_message=target_msg,
            ),
        )

        await dispatcher.feed_update(bot, update)

        admin_msg = next(
            (c for c in fake_tg.get_calls("sendMessage") if str(c.params.get("chat_id", "")) == str(SUPER_ADMIN_ID)),
            None,
        )
        assert admin_msg is not None
        admin_text = admin_msg.params.get("text", "")
        assert "Жалоба" in admin_text
        assert str(TARGET_USER_ID) in admin_text
        assert "Перейти к сообщению" in admin_text

    async def test_spam_is_no_longer_a_name_for_complaining(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
    ):
        """`/spam` from an ordinary member forwards nothing.

        It was a second name for `/report`, sitting one character away from
        `!spam`, which banned the person out of every chat. A member typing it
        now gets no report chat entry — and `!spam` answers with the move
        notice instead of acting.
        """
        update = Update(
            update_id=4,
            message=Message(
                message_id=52,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter"),
                text="/spam",
                entities=[MessageEntity(type="bot_command", offset=0, length=5)],
                reply_to_message=Message(
                    message_id=32,
                    date=datetime.now(UTC),
                    chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                    from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
                    text="Spam message",
                ),
            ),
        )

        await dispatcher.feed_update(bot, update)

        forwarded = [
            c for c in fake_tg.get_calls("sendMessage") if str(c.params.get("chat_id", "")) == str(SUPER_ADMIN_ID)
        ]
        assert forwarded == []


@pytest.mark.e2e
class TestManagedChatsMiddleware:
    """Tests for the managed chats filtering."""

    async def test_unapproved_chat_is_recorded_without_public_actions(
        self,
        bot: Bot,
        db_session_maker: async_sessionmaker[AsyncSession],
        fake_tg: FakeTelegramServer,
    ):
        """Bot records discovered chats but does not interact until approved."""
        UNMANAGED_CHAT_ID = -1009999999999
        fake_tg.set_chat_admins(UNMANAGED_CHAT_ID, [777777777])  # no super admin

        dp = Dispatcher()
        dp.update.middleware(DependenciesMiddleware(session_pool=db_session_maker, bot=bot))
        dp.update.middleware(ManagedChatsMiddleware())
        dp.update.middleware(HistoryMiddleware())
        dp.update.middleware(ApprovedChatGateMiddleware())
        dp.include_router(_build_router())

        update = Update(
            update_id=20,
            message=Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=UNMANAGED_CHAT_ID, type="supergroup", title="Unmanaged"),
                from_user=User(id=111, is_bot=False, first_name="Random"),
                text="Hello",
            ),
        )

        await dp.feed_update(bot, update)

        leave_calls = fake_tg.get_calls("leaveChat")
        assert leave_calls == []

        async with db_session_maker() as session:
            chat = await session.get(DbChat, UNMANAGED_CHAT_ID)
            assert chat is not None
            assert chat.resource_status == DbChat.STATUS_DISCOVERED

            stored_message = await session.scalar(
                select(DbMessage).where(
                    DbMessage.chat_id == UNMANAGED_CHAT_ID,
                    DbMessage.message_id == 1,
                )
            )
            assert stored_message is not None


@pytest.mark.e2e
class TestHistoryCapture:
    """What `HistoryMiddleware` leaves behind once an update is over."""

    async def test_ad_signal_outlives_the_update(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        db_session_maker: async_sessionmaker[AsyncSession],
    ):
        """The detector's row is committed, not left for a handler to maybe commit.

        No handler answers plain chatter, so nothing after the middleware
        commits the session: a row merely added to it is rolled back when the
        update ends, which is how `spam_pings` stayed empty in production.
        """
        update = Update(
            update_id=30,
            message=Message(
                message_id=60,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
                text="Заходите к нам: t.me/cheap_diplomas",
            ),
        )

        await dispatcher.feed_update(bot, update)

        async with db_session_maker() as session:
            pings = (await session.scalars(select(SpamPing).where(SpamPing.message_id == 60))).all()
        assert [p.chat_id for p in pings] == [CHAT_ID]

    async def test_private_message_is_neither_stored_nor_screened(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        db_session_maker: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """A conversation with the bot is not a chat it moderates.

        Approval is decided only for groups, so a private chat used to fall
        through as approved: its text went into `messages` and through the spam
        check, whose warning addresses moderators who are not in the room.
        """
        screened: list[int] = []

        async def _detect_spam(_db: object, message: Message) -> bool:
            screened.append(message.message_id)
            return False

        monkeypatch.setattr(spam_service, "detect_spam", _detect_spam)

        update = Update(
            update_id=31,
            message=Message(
                message_id=61,
                date=datetime.now(UTC),
                chat=Chat(id=REPORTER_ID, type="private", first_name="Reporter"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter"),
                text="Привет, вот мой канал t.me/my_channel",
            ),
        )

        await dispatcher.feed_update(bot, update)

        assert screened == []
        async with db_session_maker() as session:
            stored = await session.scalar(select(DbMessage).where(DbMessage.chat_id == REPORTER_ID))
            pings = (await session.scalars(select(SpamPing).where(SpamPing.chat_id == REPORTER_ID))).all()
        assert stored is None
        assert pings == []


@pytest.mark.e2e
class TestHistoryUnderContention:
    """A new member's first messages often arrive together: an album, a burst."""

    async def test_a_user_another_update_just_created_is_merged_not_inserted_twice(
        self, db_session_maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Read-then-insert lost the race: both updates saw no row and both inserted."""
        from app.db.models import User as DbUser
        from app.db.repositories.user import UserRepository
        from app.moderation import history_service

        async with db_session_maker() as session:
            session.add(DbUser(id=TARGET_USER_ID, first_name="Old"))
            await session.commit()

        async def not_there_yet(self, user_id):
            return None  # what the other update saw a moment ago

        monkeypatch.setattr(UserRepository, "get_by_id", not_there_yet)
        monkeypatch.setattr(UserRepository, "_get_user_model", not_there_yet)

        async with db_session_maker() as session:
            await history_service.merge_user(session, User(id=TARGET_USER_ID, is_bot=False, first_name="New"))

        async with db_session_maker() as session:
            stored = await session.get(DbUser, TARGET_USER_ID)
        assert stored is not None
        assert stored.first_name == "New"

    async def test_a_failed_write_does_not_lose_the_rest_of_the_update(
        self, dispatcher: Dispatcher, bot: Bot, db_session_maker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A swallowed database error left the session failed, and the update died at the next query."""
        from app.db.models import User as DbUser
        from app.moderation import history_service

        async with db_session_maker() as session:
            session.add(DbUser(id=TARGET_USER_ID, first_name="Existing"))
            await session.commit()

        async def failing_merge(db, user):
            db.add(DbUser(id=TARGET_USER_ID, first_name="Duplicate"))
            await db.flush()  # IntegrityError, and the session now needs a rollback

        monkeypatch.setattr(history_service, "merge_user", failing_merge)
        update = Update(
            update_id=40,
            message=Message(
                message_id=70,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
                text="hello",
            ),
        )

        await dispatcher.feed_update(bot, update)

        async with db_session_maker() as session:
            stored = await session.scalar(select(DbMessage).where(DbMessage.message_id == 70))
        assert stored is not None


@pytest.mark.e2e
class TestSpamWarning:
    async def test_a_first_message_matching_known_spam_is_flagged(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
    ) -> None:
        """The message was saved before the check counted earlier ones, so it counted itself."""
        spam_text = "Дешёвые дипломы любого вуза, пишите в личку"
        async with db_session_maker() as session:
            session.add(
                DbMessage(
                    chat_id=CHAT_ID, user_id=999000999, message_id=5, message=spam_text, message_info={}, spam=True
                )
            )
            await session.commit()

        update = Update(
            update_id=50,
            message=Message(
                message_id=80,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=333000333, is_bot=False, first_name="Newcomer"),
                text=spam_text,
            ),
        )

        await dispatcher.feed_update(bot, update)

        texts = [str(c.params.get("text", "")) for c in fake_tg.get_calls("sendMessage")]
        assert any("Похоже на спам" in t for t in texts)

    async def test_a_regular_writing_the_same_text_is_not_flagged(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
    ) -> None:
        spam_text = "Дешёвые дипломы любого вуза, пишите в личку"
        async with db_session_maker() as session:
            session.add(
                DbMessage(
                    chat_id=CHAT_ID, user_id=999000999, message_id=5, message=spam_text, message_info={}, spam=True
                )
            )
            session.add(DbMessage(chat_id=CHAT_ID, user_id=333000333, message_id=6, message="привет", message_info={}))
            await session.commit()

        update = Update(
            update_id=51,
            message=Message(
                message_id=81,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=333000333, is_bot=False, first_name="Regular"),
                text=spam_text,
            ),
        )

        await dispatcher.feed_update(bot, update)

        texts = [str(c.params.get("text", "")) for c in fake_tg.get_calls("sendMessage")]
        assert not any("Похоже на спам" in t for t in texts)


@pytest.mark.e2e
class TestGateOnButtons:
    async def test_a_button_pressed_in_an_unapproved_chat_does_nothing(
        self, bot: Bot, db_session_maker: async_sessionmaker[AsyncSession], fake_tg: FakeTelegramServer
    ) -> None:
        """Approval is a property of the chat, and a press is an update like any other."""
        from aiogram.types import CallbackQuery
        from app.presentation.telegram.bot import build_dispatcher
        from app.presentation.telegram.handlers import router
        from app.presentation.telegram.utils import BlacklistConfirm

        router._parent_router = None
        for sub in router.sub_routers:
            sub._parent_router = router
        dp = build_dispatcher(bot, db_session_maker)
        unapproved = Chat(id=-1008888888888, type="supergroup", title="Not ours")
        async with db_session_maker() as session:
            session.add(DbChat(id=unapproved.id, title="Not ours", resource_status=DbChat.STATUS_DISCOVERED))
            await session.commit()

        press = Update(
            update_id=60,
            callback_query=CallbackQuery(
                id="cb-1",
                from_user=User(id=SUPER_ADMIN_ID, is_bot=False, first_name="Admin"),
                chat_instance="1",
                data=BlacklistConfirm(user_id=TARGET_USER_ID, chat_id=unapproved.id, message_id=30).pack(),
                message=Message(
                    message_id=90,
                    date=datetime.now(UTC),
                    chat=unapproved,
                    from_user=User(id=123456, is_bot=True, first_name="Bot"),
                    text="Забанить во всех одобренных чатах?",
                ),
            ),
        )

        await dp.feed_update(bot, press)
        router._parent_router = None

        assert fake_tg.get_calls("banChatMember") == []
        assert fake_tg.get_calls("deleteMessage") == []


@pytest.mark.e2e
class TestReportThrottle:
    async def test_a_member_cannot_flood_the_super_admin_with_reports(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
    ) -> None:
        """Each /report was a DM to the super admin, and the command was deleted, so nobody saw the flood."""
        from app.presentation.telegram.handlers import groups

        groups.forget_reports()
        target = Message(
            message_id=31,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
            from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
            text="anything",
        )
        for update_id in range(70, 75):
            report = Message(
                message_id=update_id,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=REPORTER_ID, is_bot=False, first_name="Reporter"),
                text="/report",
                entities=[MessageEntity(type="bot_command", offset=0, length=7)],
                reply_to_message=target,
            )
            await dispatcher.feed_update(bot, Update(update_id=update_id, message=report))

        to_admin = [c for c in fake_tg.get_calls("sendMessage") if str(c.params.get("chat_id")) == str(SUPER_ADMIN_ID)]
        assert len(to_admin) == 1


@pytest.mark.e2e
class TestSupergroupUpgrade:
    async def test_a_group_upgraded_to_a_supergroup_keeps_its_moderation(
        self, dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
    ) -> None:
        """Telegram gives the upgraded chat a new id; everything stayed on the dead one."""
        from app.db.repositories import get_admin_repository

        old_id, new_id, child_id, moderator = -4555123, -1004555123000, -1004555999000, 444000444
        async with db_session_maker() as session:
            session.add(
                DbChat(
                    id=old_id,
                    title="ČVUT FIT",
                    resource_status=DbChat.STATUS_APPROVED,
                    public_link="https://t.me/cvut_fit",
                    institution_code="cvut",
                )
            )
            await session.flush()
            session.add(
                DbChat(id=child_id, title="FIT 1st year", resource_status=DbChat.STATUS_APPROVED, parent_chat_id=old_id)
            )
            await session.commit()
            await get_admin_repository(session).grant(moderator, old_id)

        upgraded = Chat(id=new_id, type="supergroup", title="ČVUT FIT")
        service = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=upgraded,
            from_user=User(id=SUPER_ADMIN_ID, is_bot=False, first_name="Admin"),
            migrate_from_chat_id=old_id,
        )
        await dispatcher.feed_update(bot, Update(update_id=80, message=service))

        async with db_session_maker() as session:
            new = await session.get(DbChat, new_id)
            old = await session.get(DbChat, old_id)
            child = await session.get(DbChat, child_id)
            assert new is not None
            assert (new.resource_status, new.public_link, new.institution_code) == (
                DbChat.STATUS_APPROVED,
                "https://t.me/cvut_fit",
                "cvut",
            )
            assert old is not None
            assert (old.resource_status, old.public_link) == (DbChat.STATUS_DISABLED, None)
            assert child is not None
            assert child.parent_chat_id == new_id
            assert await get_admin_repository(session).is_admin_in(moderator, new_id)

        ban = Message(
            message_id=2,
            date=datetime.now(UTC),
            chat=upgraded,
            from_user=User(id=moderator, is_bot=False, first_name="Mod"),
            text="!ban",
            entities=[MessageEntity(type="bot_command", offset=0, length=4)],
            reply_to_message=Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=upgraded,
                from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="T"),
                text="x",
            ),
        )
        await dispatcher.feed_update(bot, Update(update_id=81, message=ban))
        assert [int(c.params["user_id"]) for c in fake_tg.get_calls("banChatMember")] == [TARGET_USER_ID]


@pytest.mark.e2e
class TestHistoryIsOneRowPerMessage:
    async def test_a_redelivered_update_is_stored_once(
        self, dispatcher: Dispatcher, bot: Bot, db_session_maker
    ) -> None:
        """Telegram redelivers what it was not sure arrived; each copy was a new row."""
        from sqlalchemy import func

        update = Update(
            update_id=90,
            message=Message(
                message_id=95,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="supergroup", title="Test Chat"),
                from_user=User(id=TARGET_USER_ID, is_bot=False, first_name="Target"),
                text="hello",
            ),
        )

        await dispatcher.feed_update(bot, update)
        await dispatcher.feed_update(bot, update)

        async with db_session_maker() as session:
            stored = await session.scalar(select(func.count()).select_from(DbMessage).where(DbMessage.message_id == 95))
        assert stored == 1
