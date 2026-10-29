"""What each person is in each chat follows Telegram's membership updates.

Only the current state is kept. Administrators are also checked once a day,
because an update lost to a downtime would otherwise leave a demoted admin
recorded as one for good.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import (
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
    Update,
    User,
)
from app.chats import members
from app.db.models import ChatMember
from app.db.models import User as DbUser
from app.presentation.telegram.middlewares.chat_state import ChatStateMiddleware
from sqlalchemy import select

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
JAN = User(id=60606, is_bot=False, first_name="Jan", username="jans", language_code="cs", is_premium=True)
OWNER = User(id=7, is_bot=False, first_name="Owner")
BOT_ID = 42
T0 = datetime.datetime(2026, 10, 29, 12, 0)

_PERMISSIONS = {
    "can_send_messages": False,
    "can_send_audios": False,
    "can_send_documents": False,
    "can_send_photos": False,
    "can_send_videos": False,
    "can_send_video_notes": False,
    "can_send_voice_notes": False,
    "can_send_polls": False,
    "can_send_other_messages": False,
    "can_add_web_page_previews": False,
    "can_change_info": False,
    "can_invite_users": False,
    "can_pin_messages": False,
    "can_manage_topics": False,
    "can_edit_tag": False,
    "can_react_to_messages": False,
}


def _restricted(user: User = JAN, until: int = 0) -> ChatMemberRestricted:
    return ChatMemberRestricted.model_validate(
        {"user": user, "is_member": True, "until_date": until, **_PERMISSIONS}, context={"bot": None}
    )


def _admin(user: User) -> ChatMemberAdministrator:
    rights = dict.fromkeys(
        (
            "can_be_edited",
            "is_anonymous",
            "can_manage_chat",
            "can_delete_messages",
            "can_manage_video_chats",
            "can_restrict_members",
            "can_promote_members",
            "can_change_info",
            "can_invite_users",
            "can_post_stories",
            "can_edit_stories",
            "can_delete_stories",
            "can_send_welcome_messages",
        ),
        True,
    )
    return ChatMemberAdministrator.model_validate({"user": user, **rights})


async def test_a_join_and_a_mute_leave_only_the_current_state(session) -> None:
    await members.record(session, CHAT_ID, ChatMemberMember(user=JAN), at=T0)
    await members.record(session, CHAT_ID, _restricted(), at=T0 + datetime.timedelta(minutes=1))

    row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert row.status == "restricted"
    assert row.rights["is_member"] is True
    assert row.rights["can_send_messages"] is False
    # Telegram's 0 is "for good": no date, rather than 1970.
    assert row.until_date is None
    assert row.changed_at == T0 + datetime.timedelta(minutes=1)


async def test_a_ban_keeps_its_end(session) -> None:
    until = int(datetime.datetime(2026, 11, 5, tzinfo=datetime.UTC).timestamp())
    banned = ChatMemberBanned.model_validate({"user": JAN, "until_date": until})

    await members.record(session, CHAT_ID, banned, at=T0)

    row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert (row.status, row.until_date) == ("kicked", datetime.datetime(2026, 11, 5))


async def test_an_older_update_changes_nothing_and_the_same_state_only_confirms(session) -> None:
    await members.record(session, CHAT_ID, _restricted(), at=T0)
    await members.record(session, CHAT_ID, ChatMemberMember(user=JAN), at=T0 - datetime.timedelta(minutes=1))
    await members.record(session, CHAT_ID, _restricted(), at=T0 + datetime.timedelta(hours=1))

    row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert row.status == "restricted"
    assert (row.changed_at, row.known_at) == (T0, T0 + datetime.timedelta(hours=1))


def _chat_member_update(chat_type: str = "supergroup") -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "chat_member": {
                "chat": {"id": CHAT_ID, "type": chat_type, "title": "ČVUT FIT"},
                "from": OWNER.model_dump(exclude_none=True),
                "date": int(T0.replace(tzinfo=datetime.UTC).timestamp()),
                "old_chat_member": {"status": "left", "user": JAN.model_dump(exclude_none=True)},
                "new_chat_member": {"status": "member", "user": JAN.model_dump(exclude_none=True)},
            },
        }
    )


async def test_the_middleware_records_the_member_and_both_people(session) -> None:
    handler = AsyncMock(return_value="handled")

    assert await ChatStateMiddleware()(handler, _chat_member_update(), {"db": session}) == "handled"

    row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert (row.status, row.known_at) == ("member", T0)
    jan = await session.get(DbUser, JAN.id)
    assert (jan.username, jan.language_code, jan.is_premium) == ("jans", "cs", True)
    assert await session.get(DbUser, OWNER.id) is not None


async def test_a_language_left_out_keeps_the_last_one(session) -> None:
    from app.moderation import history_service

    await history_service.merge_user(session, JAN)
    await history_service.merge_user(session, User(id=JAN.id, is_bot=False, first_name="Jan", username="jans"))

    jan = await session.get(DbUser, JAN.id)
    await session.refresh(jan)
    assert (jan.language_code, jan.is_premium) == ("cs", False)


def _bot(admins: list, members_by_id: dict[int, object]) -> MagicMock:
    bot = MagicMock(id=BOT_ID)
    bot.get_chat_administrators = AsyncMock(return_value=admins)
    bot.get_chat_member = AsyncMock(side_effect=lambda _chat_id, user_id: members_by_id[user_id])
    return bot


async def test_the_daily_check_finds_a_demotion_the_updates_missed(session_maker) -> None:
    gone_admin = User(id=8, is_bot=False, first_name="Ex")
    other_bot = User(id=9, is_bot=True, first_name="Guard")
    async with session_maker() as session:
        for user in (gone_admin, other_bot):
            await members.record(session, CHAT_ID, _admin(user), at=T0)
    bot = _bot(
        admins=[ChatMemberOwner(user=OWNER, is_anonymous=False)],
        members_by_id={gone_admin.id: ChatMemberMember(user=gone_admin), other_bot.id: _admin(other_bot)},
    )
    at = T0 + datetime.timedelta(days=1)

    await members.check_administrators(session_maker=session_maker, bot=bot, chat_id=CHAT_ID, at=at)

    async with session_maker() as session:
        assert (await session.get(ChatMember, (CHAT_ID, OWNER.id))).status == "creator"
        assert (await session.get(ChatMember, (CHAT_ID, gone_admin.id))).status == "member"
        # A bot never shows on the list; asked on its own, it is still an administrator.
        guard = await session.get(ChatMember, (CHAT_ID, other_bot.id))
        assert (guard.status, guard.known_at) == ("administrator", at)
    assert sorted(call.args[1] for call in bot.get_chat_member.await_args_list) == [gone_admin.id, other_bot.id]


async def test_in_the_same_second_the_later_update_wins_whatever_order_they_arrive(session) -> None:
    """The captcha mutes and admits within a second; handled at once, the admit may be recorded first."""
    muted = ChatMemberRestricted.model_validate({"user": JAN, "is_member": False, "until_date": 0, **_PERMISSIONS})
    admitted = _restricted()

    await members.record(session, CHAT_ID, admitted, at=T0, update_id=11)
    await members.record(session, CHAT_ID, muted, at=T0, update_id=10)

    row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert (row.rights["is_member"], row.update_id) == (True, 11)


async def test_the_daily_check_does_not_overrule_an_update_from_the_same_second(session) -> None:
    await members.record(session, CHAT_ID, _restricted(), at=T0, update_id=11)

    await members.record(session, CHAT_ID, ChatMemberMember(user=JAN), at=T0)

    assert (await session.get(ChatMember, (CHAT_ID, JAN.id))).status == "restricted"


async def test_the_daily_check_asks_only_about_administrators_and_survives_a_refusal(session_maker) -> None:
    from aiogram.exceptions import TelegramBadRequest

    refusing = User(id=8, is_bot=False, first_name="Deleted")
    gone_admin = User(id=10, is_bot=False, first_name="Ex")
    plain = User(id=11, is_bot=False, first_name="Plain")
    async with session_maker() as session:
        for user in (refusing, gone_admin):
            await members.record(session, CHAT_ID, _admin(user), at=T0)
        await members.record(session, CHAT_ID, ChatMemberMember(user=plain), at=T0)

    def answer(_chat_id: int, user_id: int):
        if user_id == refusing.id:
            raise TelegramBadRequest(method=MagicMock(), message="user not found")
        return ChatMemberMember(user=gone_admin)

    bot = _bot(admins=[], members_by_id={})
    bot.get_chat_member = AsyncMock(side_effect=answer)

    await members.check_administrators(
        session_maker=session_maker, bot=bot, chat_id=CHAT_ID, at=T0 + datetime.timedelta(days=1)
    )

    # Not the plain member: members are too many to ask about one by one.
    assert [call.args[1] for call in bot.get_chat_member.await_args_list] == [refusing.id, gone_admin.id]
    async with session_maker() as session:
        assert (await session.get(ChatMember, (CHAT_ID, gone_admin.id))).status == "member"


def _update(**payload) -> Update:
    return Update.model_validate({"update_id": 1, **payload})


async def test_a_join_request_and_a_button_press_record_the_person(session) -> None:
    request = {
        "chat": {"id": CHAT_ID, "type": "supergroup", "title": "ČVUT FIT"},
        "from": JAN.model_dump(exclude_none=True),
        "user_chat_id": JAN.id,
        "date": int(T0.replace(tzinfo=datetime.UTC).timestamp()),
    }
    pressed = {"id": "q", "from": OWNER.model_dump(exclude_none=True), "chat_instance": "c", "data": "x"}

    for update in (_update(chat_join_request=request), _update(callback_query=pressed)):
        await ChatStateMiddleware()(AsyncMock(), update, {"db": session})

    assert await session.get(DbUser, JAN.id) is not None
    assert await session.get(DbUser, OWNER.id) is not None


async def test_a_channels_subscribers_are_not_recorded(session) -> None:
    handler = AsyncMock()

    await ChatStateMiddleware()(handler, _chat_member_update("channel"), {"db": session})

    handler.assert_awaited_once()
    assert await session.get(ChatMember, (CHAT_ID, JAN.id)) is None
    assert await session.get(DbUser, JAN.id) is None


async def test_a_failure_to_record_rolls_back_and_passes_the_update_on(session, monkeypatch) -> None:
    async def broken(db, *args, **kwargs) -> None:
        await db.execute(select(ChatMember))
        raise RuntimeError("db down")

    monkeypatch.setattr(members, "record", broken)
    handler = AsyncMock(return_value="handled")

    assert await ChatStateMiddleware()(handler, _chat_member_update(), {"db": session}) == "handled"
    assert not session.in_transaction()
