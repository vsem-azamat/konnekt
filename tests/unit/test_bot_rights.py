"""The bot's status and rights in each chat follow Telegram's updates, with a history.

Telegram tells the bot whenever its own membership changes; the daily check
asks about chats no update has confirmed lately.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ChatMemberAdministrator, ChatMemberLeft, ChatMemberMember, Update, User
from app.chats import bot_rights
from app.chats.rights import DEFAULT_ADMIN_RIGHTS
from app.core.time import utc_now
from app.db.models import Chat, ChatBotRights, ChatBotRightsChange
from app.presentation.telegram.middlewares.chat_state import ChatStateMiddleware
from sqlalchemy import select

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
BOT = User(id=42, is_bot=True, first_name="Konnekt")
OWNER = 7
T0 = datetime.datetime(2026, 10, 29, 12, 0)


def _admin(**overrides: bool) -> ChatMemberAdministrator:
    rights = {k: v for k, v in DEFAULT_ADMIN_RIGHTS.model_dump().items() if isinstance(v, bool)}
    return ChatMemberAdministrator.model_validate({"user": BOT, "can_be_edited": False, **rights, **overrides})


async def _changes(session) -> list[ChatBotRightsChange]:
    return list((await session.scalars(select(ChatBotRightsChange).order_by(ChatBotRightsChange.id))).all())


async def test_the_first_update_records_the_state_and_its_history(session) -> None:
    await bot_rights.record(session, CHAT_ID, _admin(), at=T0, by=OWNER)

    row = await session.get(ChatBotRights, CHAT_ID)
    assert row is not None
    assert row.status == "administrator"
    assert row.rights["can_restrict_members"] is True
    assert row.rights["can_promote_members"] is False
    [change] = await _changes(session)
    assert (change.status, change.changed_by, change.changed_at) == ("administrator", OWNER, T0)


async def test_the_same_state_again_only_confirms_it(session) -> None:
    await bot_rights.record(session, CHAT_ID, _admin(), at=T0)
    later = T0 + datetime.timedelta(hours=1)

    await bot_rights.record(session, CHAT_ID, _admin(), at=later)

    row = await session.get(ChatBotRights, CHAT_ID)
    assert (row.changed_at, row.known_at) == (T0, later)
    assert len(await _changes(session)) == 1


async def test_a_lost_right_is_a_change_with_who_made_it(session) -> None:
    await bot_rights.record(session, CHAT_ID, _admin(), at=T0)
    later = T0 + datetime.timedelta(minutes=5)

    await bot_rights.record(session, CHAT_ID, _admin(can_invite_users=False), at=later, by=OWNER)

    row = await session.get(ChatBotRights, CHAT_ID)
    assert row.rights["can_invite_users"] is False
    assert row.changed_at == later
    changes = await _changes(session)
    assert [c.rights["can_invite_users"] for c in changes] == [True, False]
    assert changes[-1].changed_by == OWNER


async def test_being_removed_is_a_status_with_no_rights(session) -> None:
    await bot_rights.record(session, CHAT_ID, _admin(), at=T0)

    await bot_rights.record(session, CHAT_ID, ChatMemberLeft(user=BOT), at=T0 + datetime.timedelta(minutes=1))

    row = await session.get(ChatBotRights, CHAT_ID)
    assert (row.status, row.rights) == ("left", {})


async def test_an_update_older_than_what_is_stored_changes_nothing(session) -> None:
    await bot_rights.record(session, CHAT_ID, _admin(), at=T0)

    await bot_rights.record(session, CHAT_ID, ChatMemberMember(user=BOT), at=T0 - datetime.timedelta(minutes=1))

    row = await session.get(ChatBotRights, CHAT_ID)
    assert row.status == "administrator"
    assert len(await _changes(session)) == 1


def _my_chat_member(chat_type: str = "supergroup") -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "my_chat_member": {
                "chat": {"id": CHAT_ID, "type": chat_type, "title": "ČVUT FIT"},
                "from": {"id": OWNER, "is_bot": False, "first_name": "Owner"},
                "date": int(T0.replace(tzinfo=datetime.UTC).timestamp()),
                "old_chat_member": {"status": "member", "user": BOT.model_dump(exclude_none=True)},
                "new_chat_member": _admin().model_dump(mode="json", exclude_none=True),
            },
        }
    )


async def test_the_middleware_records_the_bots_own_update_and_passes_it_on(session) -> None:
    handler = AsyncMock(return_value="handled")

    result = await ChatStateMiddleware()(handler, _my_chat_member(), {"db": session})

    assert result == "handled"
    row = await session.get(ChatBotRights, CHAT_ID)
    assert (row.status, row.known_at) == ("administrator", T0)
    assert (await _changes(session))[0].changed_by == OWNER


async def test_a_private_chat_is_not_a_chat_the_bot_is_in(session) -> None:
    handler = AsyncMock()

    await ChatStateMiddleware()(handler, _my_chat_member("private"), {"db": session})

    handler.assert_awaited_once()
    assert await session.get(ChatBotRights, CHAT_ID) is None


async def test_a_failure_to_record_never_drops_the_update(session, monkeypatch) -> None:
    async def broken(db, *args, **kwargs) -> None:
        await db.execute(select(Chat).where(Chat.id == 1))
        raise RuntimeError("db down")

    monkeypatch.setattr(bot_rights, "record", broken)
    handler = AsyncMock(return_value="handled")

    assert await ChatStateMiddleware()(handler, _my_chat_member(), {"db": session}) == "handled"
    # Rolled back, so the handlers after it still have a session to work with.
    assert not session.in_transaction()


def _bot(answer=None) -> MagicMock:
    bot = MagicMock(id=BOT.id)
    bot.get_chat_member = AsyncMock(side_effect=answer or (lambda *_: _admin()))
    bot.get_chat_administrators = AsyncMock(return_value=[])
    return bot


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings.chat_state, "pause_between_chats_seconds", 0)


async def test_the_check_asks_only_chats_not_confirmed_lately(session_maker) -> None:
    fresh, stale, unknown, preview, migrated, absent = -1001, -1002, -1003, Chat.preview_id_for("abc"), -1005, -1006
    async with session_maker() as session:
        for chat_id in (fresh, stale, unknown, migrated, absent):
            session.add(Chat(id=chat_id))
        session.add(Chat(id=preview, resource_status=Chat.STATUS_EXTERNAL))
        session.add(Chat(id=-1007, resource_status=Chat.STATUS_EXTERNAL, kind=Chat.KIND_CHANNEL))
        await session.flush()
        (await session.get(Chat, migrated)).migrated_to_chat_id = -1009
        (await session.get(Chat, absent)).bot_absent_at = utc_now()
        session.add(ChatBotRights(chat_id=fresh, status="administrator", rights={}, changed_at=T0, known_at=utc_now()))
        long_ago = utc_now() - datetime.timedelta(days=2)
        session.add(
            ChatBotRights(chat_id=stale, status="administrator", rights={}, changed_at=long_ago, known_at=long_ago)
        )
        await session.commit()
    bot = _bot()

    assert await bot_rights.check_once(session_maker=session_maker, bot=bot) == 2

    assert sorted(call.args[0] for call in bot.get_chat_member.await_args_list) == sorted([stale, unknown])
    async with session_maker() as session:
        assert (await session.get(ChatBotRights, unknown)).status == "administrator"
        # The stale row had no rights recorded: Telegram's answer is a change.
        assert (await session.get(ChatBotRights, stale)).rights["can_restrict_members"] is True


async def test_a_refusing_chat_is_skipped_and_flood_control_ends_the_tick(session_maker) -> None:
    async with session_maker() as session:
        for chat_id in (-1003, -1002, -1001):
            session.add(Chat(id=chat_id))
        await session.commit()

    def answer(chat_id: int, user_id: int):
        if chat_id == -1003:
            raise TelegramBadRequest(method=MagicMock(), message="chat not found")
        raise TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=600)

    assert await bot_rights.check_once(session_maker=session_maker, bot=_bot(answer)) == 2

    async with session_maker() as session:
        assert (await session.scalars(select(ChatBotRights))).all() == []


async def test_the_gauge_counts_approved_chats_by_what_the_bot_lacks(session) -> None:
    from app.chats.metrics import BOT_RIGHTS_MISSING

    rows = {
        -1001: ("administrator", _admin().model_dump()),
        -1002: ("administrator", _admin(can_invite_users=False, can_delete_messages=False).model_dump()),
        -1003: ("member", {}),
        -1004: ("kicked", {}),
        -1005: ("creator", {}),
    }
    for chat_id, (status, rights) in rows.items():
        session.add(Chat(id=chat_id, resource_status=Chat.STATUS_APPROVED))
        rights = {k: v for k, v in rights.items() if isinstance(v, bool)}
        session.add(ChatBotRights(chat_id=chat_id, status=status, rights=rights, changed_at=T0, known_at=T0))
    session.add(Chat(id=-1006, resource_status=Chat.STATUS_APPROVED))
    # Not moderated: what the bot lacks there is nobody's alert.
    session.add(Chat(id=-1007, resource_status=Chat.STATUS_OBSERVED))
    session.add(ChatBotRights(chat_id=-1007, status="member", rights={}, changed_at=T0, known_at=T0))
    await session.commit()

    await bot_rights.refresh_gauge(session)

    def value(problem: str) -> float:
        return BOT_RIGHTS_MISSING.labels(problem=problem)._value.get()

    assert {p: value(p) for p in bot_rights.PROBLEMS} == {
        "left": 1,
        "not_admin": 1,
        "no_delete": 1,
        "no_restrict": 0,
        "no_invite": 1,
        "unknown": 1,
    }


async def test_a_removed_bot_is_recorded_and_asked_again_only_when_due(session_maker) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1001))
        session.add(Chat(id=-1002))
        await session.commit()

    def answer(chat_id: int, user_id: int):
        message = (
            "bot was kicked from the supergroup chat"
            if chat_id == -1001
            else "bot is not a member of the supergroup chat"
        )
        raise TelegramForbiddenError(method=MagicMock(), message=message)

    bot = _bot(answer)
    assert await bot_rights.check_once(session_maker=session_maker, bot=bot) == 2

    async with session_maker() as session:
        assert (await session.get(ChatBotRights, -1001)).status == "kicked"
        assert (await session.get(ChatBotRights, -1002)).status == "left"
    # Just confirmed: not asked again within the day.
    assert await bot_rights.check_once(session_maker=session_maker, bot=bot) == 0

    async with session_maker() as session:
        for row in (await session.scalars(select(ChatBotRights))).all():
            row.known_at = utc_now() - datetime.timedelta(days=30)
        await session.commit()
    # Due again, in case an update adding the bot back was lost; the same answer adds no history.
    assert await bot_rights.check_once(session_maker=session_maker, bot=bot) == 2
    async with session_maker() as session:
        assert len(await _changes(session)) == 2


async def test_the_check_stamps_whole_seconds_so_a_change_right_after_still_counts(session_maker) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1001))
        await session.commit()

    await bot_rights.check_once(session_maker=session_maker, bot=_bot())

    async with session_maker() as session:
        assert (await session.get(ChatBotRights, -1001)).known_at.microsecond == 0


async def test_the_check_asks_for_the_administrators_only_where_the_bot_is_one(session_maker) -> None:
    async with session_maker() as session:
        session.add(Chat(id=-1001))
        session.add(Chat(id=-1002))
        await session.commit()
    bot = _bot(lambda chat_id, _user_id: _admin() if chat_id == -1001 else ChatMemberMember(user=BOT))

    await bot_rights.check_once(session_maker=session_maker, bot=bot)

    assert [call.args[0] for call in bot.get_chat_administrators.await_args_list] == [-1001]


async def test_a_refused_administrators_list_skips_that_chat_and_flood_control_ends_the_tick(session_maker) -> None:
    async with session_maker() as session:
        for chat_id in (-1003, -1002, -1001):
            session.add(Chat(id=chat_id))
        await session.commit()
    bot = _bot()

    def listing(chat_id: int):
        if chat_id == -1003:
            raise TelegramBadRequest(method=MagicMock(), message="chat not found")
        raise TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=600)

    bot.get_chat_administrators = AsyncMock(side_effect=listing)

    assert await bot_rights.check_once(session_maker=session_maker, bot=bot) == 2
    async with session_maker() as session:
        # Both asked chats still had the bot's own rights recorded.
        assert len((await session.scalars(select(ChatBotRights))).all()) == 2
