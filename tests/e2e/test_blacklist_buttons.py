"""The blacklist's buttons, and the handlers no test reached, through the production dispatcher.

`/banall` only asks; the press is where a person is banned from every chat
and, optionally, wiped. None of these presses ran in a test before, nor did
!json or /contacts (#175).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from app.db.models import Message as DbMessage
from app.db.models import ModerationEvent
from app.db.models import User as DbUser
from app.presentation.telegram.utils import BlacklistConfirm, UnblockUser
from sqlalchemy import select

from tests.e2e.conftest import APPROVED_CHAT_ID

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fake_telegram import FakeTelegramServer

pytestmark = pytest.mark.e2e

SUPER_ADMIN_ID = 123456789
MODERATOR_ID = 444000444
SPAMMER_ID = 666000666
GROUP = Chat(id=APPROVED_CHAT_ID, type="supergroup", title="Approved")


def _press(data: str, *, by: int = SUPER_ADMIN_ID) -> Update:
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="cb",
            from_user=User(id=by, is_bot=False, first_name="Presser"),
            chat_instance="1",
            data=data,
            message=Message(
                message_id=500,
                date=datetime.now(UTC),
                chat=GROUP,
                from_user=User(id=123456, is_bot=True, first_name="Bot"),
                text="Забанить во всех одобренных чатах?",
            ),
        ),
    )


@pytest.fixture
async def spammer(db_session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_maker() as session:
        session.add(DbUser(id=SPAMMER_ID, first_name="Spammer"))
        session.add(
            DbMessage(chat_id=APPROVED_CHAT_ID, user_id=SPAMMER_ID, message_id=30, message="buy now", message_info={})
        )
        await session.commit()


async def _user(db_session_maker, uid: int) -> DbUser | None:
    async with db_session_maker() as session:
        return await session.get(DbUser, uid)


async def _actions(db_session_maker) -> list[str]:
    async with db_session_maker() as session:
        return [e.action for e in (await session.scalars(select(ModerationEvent))).all()]


def _edited(fake_tg: FakeTelegramServer) -> str:
    return "\n".join(str(c.params.get("text")) for c in fake_tg.get_calls("editMessageText"))


async def test_pressing_ban_blacklists_and_bans_everywhere(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker, spammer
) -> None:
    from app.db.models import Chat as DbChat

    other_approved, unapproved = -1007000000001, -1007000000002
    async with db_session_maker() as session:
        session.add(DbChat(id=other_approved, title="Other", resource_status=DbChat.STATUS_APPROVED))
        session.add(DbChat(id=unapproved, title="Not ours", resource_status=DbChat.STATUS_DISCOVERED))
        await session.commit()
    data = BlacklistConfirm(user_id=SPAMMER_ID, chat_id=APPROVED_CHAT_ID, message_id=30).pack()

    await production_dispatcher.feed_update(bot, _press(data))

    stored = await _user(db_session_maker, SPAMMER_ID)
    assert stored is not None
    assert stored.blocked is True
    banned_in = {int(c.params["chat_id"]) for c in fake_tg.get_calls("banChatMember")}
    assert banned_in == {APPROVED_CHAT_ID, other_approved}
    assert await _actions(db_session_maker) == ["blacklist"]
    assert "черный список" in _edited(fake_tg)


async def test_pressing_ban_and_wipe_teaches_the_spam_filter(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker, spammer
) -> None:
    data = BlacklistConfirm(user_id=SPAMMER_ID, chat_id=APPROVED_CHAT_ID, message_id=30, revoke=1, mark_spam=1).pack()

    await production_dispatcher.feed_update(bot, _press(data))

    async with db_session_maker() as session:
        row = await session.scalar(select(DbMessage).where(DbMessage.message_id == 30))
    assert row is not None
    assert row.spam is True
    assert any(str(c.params.get("message_id")) == "30" for c in fake_tg.get_calls("deleteMessage"))
    assert any(str(c.params.get("revoke_messages")).lower() == "true" for c in fake_tg.get_calls("banChatMember"))


async def test_a_super_admin_cannot_be_blacklisted_by_a_stale_dialog(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    data = BlacklistConfirm(user_id=SUPER_ADMIN_ID, chat_id=APPROVED_CHAT_ID, message_id=30).pack()

    await production_dispatcher.feed_update(bot, _press(data))

    assert fake_tg.get_calls("banChatMember") == []
    assert await _actions(db_session_maker) == []


async def test_only_a_super_admin_may_press(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker, spammer
) -> None:
    """Moderating one chat does not reach every chat."""
    from app.db.repositories import get_admin_repository

    async with db_session_maker() as session:
        await get_admin_repository(session).grant(MODERATOR_ID, APPROVED_CHAT_ID)
    data = BlacklistConfirm(user_id=SPAMMER_ID, chat_id=APPROVED_CHAT_ID, message_id=30).pack()

    await production_dispatcher.feed_update(bot, _press(data, by=MODERATOR_ID))

    stored = await _user(db_session_maker, SPAMMER_ID)
    assert stored is not None
    assert stored.blocked is False
    assert fake_tg.get_calls("banChatMember") == []


async def test_unblocking_lifts_the_ban_everywhere(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    async with db_session_maker() as session:
        session.add(DbUser(id=SPAMMER_ID, first_name="Spammer", blocked=True))
        await session.commit()

    await production_dispatcher.feed_update(bot, _press(UnblockUser(user_id=SPAMMER_ID).pack()))

    stored = await _user(db_session_maker, SPAMMER_ID)
    assert stored is not None
    assert stored.blocked is False
    calls = fake_tg.get_calls("unbanChatMember")
    assert [int(c.params["user_id"]) for c in calls] == [SPAMMER_ID]
    assert str(calls[0].params["only_if_banned"]).lower() == "true"
    assert await _actions(db_session_maker) == ["unblacklist"]


async def test_cancel_does_nothing_but_say_so(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    await production_dispatcher.feed_update(bot, _press("cancel_blacklist"))

    assert fake_tg.get_calls("banChatMember") == []
    assert "отменено" in _edited(fake_tg)


async def test_the_list_turns_its_pages(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    from app.presentation.telegram.utils import BlacklistPagination

    async with db_session_maker() as session:
        for i in range(12):
            session.add(DbUser(id=700000000 + i, first_name=f"Spammer{i}", blocked=True))
        await session.commit()

    await production_dispatcher.feed_update(bot, _press(BlacklistPagination(page=1).pack()))

    assert "12 человек" in _edited(fake_tg)
    assert "Показаны 11–12 из 12" in _edited(fake_tg)


def _command(text: str, *, by: int = SUPER_ADMIN_ID, chat: Chat = GROUP) -> Update:
    from aiogram.types import MessageEntity

    name = text.split()[0]
    return Update(
        update_id=2,
        message=Message(
            message_id=600,
            date=datetime.now(UTC),
            chat=chat,
            from_user=User(id=by, is_bot=False, first_name="Sender"),
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=len(name))],
        ),
    )


async def test_json_shows_a_super_admin_the_message_and_tidies_up(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer
) -> None:
    await production_dispatcher.feed_update(bot, _command("!json"))

    sent = [str(c.params.get("text")) for c in fake_tg.get_calls("sendMessage")]
    assert any(text.startswith("<pre>") and "message_id" in text for text in sent)
    assert any(str(c.params.get("message_id")) == "600" for c in fake_tg.get_calls("deleteMessage"))


async def test_json_is_not_for_moderators(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker
) -> None:
    from app.db.repositories import get_admin_repository

    async with db_session_maker() as session:
        await get_admin_repository(session).grant(MODERATOR_ID, APPROVED_CHAT_ID)

    await production_dispatcher.feed_update(bot, _command("!json", by=MODERATOR_ID))

    assert not any(str(c.params.get("text")).startswith("<pre>") for c in fake_tg.get_calls("sendMessage"))


async def test_contacts_answer_anyone(production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer) -> None:
    await production_dispatcher.feed_update(bot, _command("/contacts", by=SPAMMER_ID))

    assert any("Контакты" in str(c.params.get("text")) for c in fake_tg.get_calls("sendMessage"))


async def test_a_text_edited_after_the_dialog_is_not_taught_as_spam(
    production_dispatcher: Dispatcher, bot: Bot, fake_tg: FakeTelegramServer, db_session_maker, spammer
) -> None:
    """A spammer who edits the ad into "Привет" before the press must not make "Привет" spam."""
    from sqlalchemy import update

    later = int(datetime.now(UTC).timestamp()) + 60
    async with db_session_maker() as session:
        await session.execute(
            update(DbMessage)
            .where(DbMessage.message_id == 30)
            .values(message="Привет", message_info={"edit_date": later})
        )
        await session.commit()
    data = BlacklistConfirm(user_id=SPAMMER_ID, chat_id=APPROVED_CHAT_ID, message_id=30, revoke=1, mark_spam=1).pack()

    await production_dispatcher.feed_update(bot, _press(data))

    async with db_session_maker() as session:
        row = await session.scalar(select(DbMessage).where(DbMessage.message_id == 30))
    assert row is not None
    assert row.spam is False
