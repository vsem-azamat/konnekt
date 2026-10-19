"""The chat audit reports what Telegram says about each chat against what the project expects.

Project chats drifted apart because nothing ever compared them: the bot held
different rights in different groups and nobody could say which. The audit is a
read-only pass that turns that into a list of findings per chat, so it can be
run again whenever drift is suspected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner, ChatMemberRestricted, User
from app.chats.audit import ChatState, audit_chats, inspect_chat
from app.db.models import Chat
from app.presentation.telegram.profile import DEFAULT_ADMIN_RIGHTS

pytestmark = pytest.mark.asyncio

BOT_ID = 5145935834
CHAT_ID = -1001000000001


def _full_rights() -> dict[str, bool]:
    return {name: bool(value) for name, value in DEFAULT_ADMIN_RIGHTS.model_dump().items() if isinstance(value, bool)}


def _admin(**overrides: bool) -> SimpleNamespace:
    return SimpleNamespace(status="administrator", **{**_full_rights(), **overrides})


def _chat_info(**overrides) -> SimpleNamespace:
    info = {
        "title": "ČVUT FIT",
        "username": None,
        "invite_link": "https://t.me/+abc",
        "description": "Чат студентов FIT",
        "pinned_message": None,
        "is_forum": False,
        "slow_mode_delay": None,
        "join_by_request": None,
        "has_protected_content": None,
        "has_visible_history": True,
        "has_hidden_members": None,
        "has_aggressive_anti_spam_enabled": None,
        "message_auto_delete_time": None,
        "linked_chat_id": None,
    }
    info.update(overrides)
    return SimpleNamespace(**info)


def _bot(*, info: SimpleNamespace | None = None, member: object | None = None) -> AsyncMock:
    bot = AsyncMock()
    bot.id = BOT_ID
    bot.get_chat.return_value = info or _chat_info()
    bot.get_chat_member.return_value = member or _admin()
    return bot


def _row(**overrides) -> Chat:
    return Chat(id=CHAT_ID, title="ČVUT FIT", **overrides)


async def test_a_chat_in_order_has_no_findings() -> None:
    state = await inspect_chat(_bot(), _row())

    assert state.findings == ()
    assert state.bot_status == "administrator"
    assert state.link == "https://t.me/+abc"


async def test_a_bot_that_is_only_a_member_is_reported() -> None:
    state = await inspect_chat(_bot(member=SimpleNamespace(status="member")), _row())

    assert "bot is not an administrator" in state.findings


async def test_missing_rights_are_named() -> None:
    bot = _bot(member=_admin(can_pin_messages=False, can_delete_messages=False))

    state = await inspect_chat(bot, _row())

    assert state.missing_rights == ("can_delete_messages", "can_pin_messages")
    assert "missing rights: can_delete_messages, can_pin_messages" in state.findings


async def test_topic_rights_matter_only_in_forums() -> None:
    bot = _bot(member=_admin(can_manage_topics=False))

    assert (await inspect_chat(bot, _row())).missing_rights == ()

    bot.get_chat.return_value = _chat_info(is_forum=True)
    assert (await inspect_chat(bot, _row())).missing_rights == ("can_manage_topics",)


async def test_a_chat_the_bot_cannot_see_is_reported_not_raised() -> None:
    bot = _bot()
    bot.get_chat.side_effect = TelegramBadRequest(method=MagicMock(), message="chat not found")

    state = await inspect_chat(bot, _row())

    assert state.reachable is False
    assert state.findings == ("bot cannot see the chat: chat not found",)


async def test_a_chat_without_any_link_is_reported() -> None:
    state = await inspect_chat(_bot(info=_chat_info(invite_link=None)), _row())

    assert "no link" in state.findings


async def test_a_public_username_is_the_link() -> None:
    state = await inspect_chat(_bot(info=_chat_info(username="cvut_fit", invite_link=None)), _row())

    assert state.link == "https://t.me/cvut_fit"
    assert state.findings == ()


async def test_a_catalogue_link_to_another_username_is_reported() -> None:
    bot = _bot(info=_chat_info(username="cvut_fit"))

    state = await inspect_chat(bot, _row(public_link="https://t.me/old_name"))

    assert "catalogue link differs from the chat's username" in state.findings


async def test_the_pinned_message_is_kept_short() -> None:
    pinned = SimpleNamespace(text="Правила чата: " + "x" * 300, caption=None)

    state = await inspect_chat(_bot(info=_chat_info(pinned_message=pinned)), _row())

    assert state.pinned is not None
    assert state.pinned.startswith("Правила чата: ")
    assert len(state.pinned) <= 120


async def test_audit_walks_every_chat_and_survives_a_refusal(session_maker) -> None:
    async with session_maker() as session:
        session.add_all([_row(), Chat(id=CHAT_ID - 1, title="Gone")])
        await session.commit()

    bot = _bot()

    async def _get_chat(chat_id: int):
        if chat_id == CHAT_ID - 1:
            raise TelegramBadRequest(method=MagicMock(), message="chat not found")
        return _chat_info()

    bot.get_chat.side_effect = _get_chat

    states = await audit_chats(session_maker=session_maker, bot=bot, pause_seconds=0)

    assert {s.chat_id: s.reachable for s in states} == {CHAT_ID: True, CHAT_ID - 1: False}


def _user() -> User:
    return User(id=BOT_ID, is_bot=True, first_name="Konnekt")


async def test_tags_omitted_by_telegram_follow_the_pin_right() -> None:
    rights = {k: v for k, v in _full_rights().items() if k != "can_manage_tags"}
    member = ChatMemberAdministrator.model_validate({"user": _user(), "can_be_edited": False, **rights})

    assert (await inspect_chat(_bot(member=member), _row())).missing_rights == ()


async def test_a_creator_lacks_nothing_even_in_a_forum() -> None:
    bot = _bot(info=_chat_info(is_forum=True), member=ChatMemberOwner(user=_user(), is_anonymous=False))

    state = await inspect_chat(bot, _row())

    assert state.missing_rights == ()
    assert state.findings == ()


async def test_a_restricted_bot_is_not_an_administrator() -> None:
    # Built without validation: only the status matters, and the type has a field per permission.
    member = ChatMemberRestricted.model_construct(user=_user(), status="restricted")

    state = await inspect_chat(_bot(member=member), _row())

    assert state.findings == ("bot is not an administrator",)


async def test_flood_control_is_not_reported_as_an_unreachable_chat() -> None:
    bot = _bot()
    bot.get_chat.side_effect = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=0)

    state = await inspect_chat(bot, _row())

    assert state.findings == ("not checked: flood control",)


async def test_a_failed_membership_lookup_keeps_the_chat_info() -> None:
    bot = _bot()
    bot.get_chat_member.side_effect = TelegramBadRequest(method=MagicMock(), message="member not found")

    state = await inspect_chat(bot, _row())

    assert state.reachable is True
    assert state.description == "Чат студентов FIT"
    assert state.findings == ("bot's membership unknown: member not found",)


async def test_usernames_compare_without_case() -> None:
    bot = _bot(info=_chat_info(username="cvut_fit"))

    state = await inspect_chat(bot, _row(public_link="https://t.me/CVUT_FIT"))

    assert state.findings == ()


async def test_a_catalogue_username_the_chat_no_longer_has_is_reported() -> None:
    state = await inspect_chat(_bot(), _row(public_link="https://t.me/old_name"))

    assert state.findings == ("catalogue links a username the chat no longer has",)


async def test_an_invite_link_in_the_catalogue_is_not_a_username() -> None:
    state = await inspect_chat(_bot(), _row(public_link="https://t.me/+abc"))

    assert state.findings == ()


# --- The template (#155) --------------------------------------------------

BOT_USERNAME = "konnekt_moder_bot"
PARENT = Chat(id=CHAT_ID - 100, title="ČVUT | ЧВУТ", institution_code="cvut", public_link="https://t.me/cvut_chat")


def _university_row() -> Chat:
    return _row(resource_status=Chat.STATUS_APPROVED, parent_chat_id=PARENT.id)


def _expected(current: str = "Чат студентов FIT") -> str:
    from app.chats.template import expected_description

    return expected_description(title="ČVUT FIT", current=current, bot=BOT_USERNAME, university=True, parent=PARENT)


async def _inspect(bot, chat: Chat) -> ChatState:
    return await inspect_chat(bot, chat, bot_username=BOT_USERNAME, parent=PARENT, university=True)


async def test_a_description_off_the_template_is_reported() -> None:
    state = await _inspect(_bot(), _university_row())

    assert state.expected_description == _expected()
    assert state.findings == ("description differs from the template",)


async def test_a_description_on_the_template_is_not_reported() -> None:
    state = await _inspect(_bot(info=_chat_info(description=_expected())), _university_row())

    assert state.findings == ()


async def test_only_approved_chats_are_held_to_the_template() -> None:
    state = await _inspect(_bot(), _row())

    assert state.expected_description is None
    assert state.findings == ()


async def test_apply_sets_the_description() -> None:
    from app.chats.audit import apply_template

    bot = _bot()
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == ["description set"]
    bot.set_chat_description.assert_awaited_once_with(chat_id=CHAT_ID, description=_expected())


async def test_apply_leaves_a_description_already_on_the_template() -> None:
    from app.chats.audit import apply_template

    bot = _bot(info=_chat_info(description=_expected()))
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == []
    bot.set_chat_description.assert_not_awaited()


async def test_apply_does_not_write_an_empty_description_over_none() -> None:
    from app.chats.audit import apply_template

    bot = _bot(info=_chat_info(description=None))
    state = await inspect_chat(bot, _row(resource_status=Chat.STATUS_APPROVED), bot_username=BOT_USERNAME)

    assert state.findings == ()
    assert await apply_template(bot, state) == []
    bot.set_chat_description.assert_not_awaited()


async def test_apply_without_the_right_leaves_the_description() -> None:
    from app.chats.audit import apply_template

    bot = _bot(member=_admin(can_change_info=False))
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == ["description: no right to change it"]
    bot.set_chat_description.assert_not_awaited()


async def test_apply_under_flood_control_says_it_did_not_set() -> None:
    from app.chats.audit import apply_template

    bot = _bot()
    bot.set_chat_description.side_effect = TelegramRetryAfter(method=MagicMock(), message="Too Many", retry_after=0)
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == ["description not set: flood control"]


async def _seed_cvut(session_maker) -> None:
    approved = Chat.STATUS_APPROVED
    async with session_maker() as session:
        session.add_all(
            [
                Chat(id=-1, title="ČVUT | ЧВУТ", institution_code="cvut", resource_status=approved),
                Chat(id=-2, title="Strahov", institution_code="cvut", resource_status=approved),
                Chat(id=-3, title="ČVUT FIT", parent_chat_id=-1, resource_status=approved),
            ]
        )
        await session.commit()


async def _audit(session_maker, **kwargs):
    bot = _bot(info=_chat_info(title=None, description="Чат для живущих в ареале Strahov"))
    bot.me.return_value = SimpleNamespace(username=BOT_USERNAME)
    return bot, await audit_chats(session_maker=session_maker, bot=bot, pause_seconds=0, **kwargs)


async def test_a_dormitory_keeps_its_text_even_when_audited_alone(session_maker) -> None:
    await _seed_cvut(session_maker)

    _, states = await _audit(session_maker, chat_ids={-2})

    assert [s.expected_description for s in states] == ["Чат для живущих в ареале Strahov"]


async def test_the_university_and_its_faculty_get_the_template(session_maker) -> None:
    await _seed_cvut(session_maker)

    _, states = await _audit(session_maker, chat_ids={-1, -3})

    first_lines = {s.chat_id: (s.expected_description or "").splitlines()[0] for s in states}
    assert first_lines == {
        -1: "🎓 Чат студентов и абитуриентов ČVUT",
        -3: "🎓 Чат студентов и абитуриентов ČVUT FIT",
    }


async def test_audit_applies_only_to_the_chats_asked_for(session_maker) -> None:
    await _seed_cvut(session_maker)

    bot, states = await _audit(session_maker, apply=True, chat_ids={-3})

    assert [s.chat_id for s in states] == [-3]
    assert [c.kwargs["chat_id"] for c in bot.set_chat_description.await_args_list] == [-3]
    assert states[0].applied == ("description set",)


async def test_the_template_uses_the_title_telegram_shows() -> None:
    stale = Chat(id=CHAT_ID, title="Old name", resource_status=Chat.STATUS_APPROVED, parent_chat_id=PARENT.id)

    state = await _inspect(_bot(info=_chat_info(title="ČVUT FIT")), stale)

    assert state.expected_description == _expected()


async def test_apply_with_unknown_rights_does_not_try() -> None:
    from app.chats.audit import apply_template

    bot = _bot()
    bot.get_chat_member.side_effect = TelegramBadRequest(method=MagicMock(), message="member not found")
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == ["description: rights unknown"]
    bot.set_chat_description.assert_not_awaited()


async def test_apply_after_a_network_error_does_not_claim_either_way() -> None:
    from aiogram.exceptions import TelegramNetworkError
    from app.chats.audit import apply_template

    bot = _bot()
    bot.set_chat_description.side_effect = TelegramNetworkError(method=MagicMock(), message="timeout")
    state = await _inspect(bot, _university_row())

    assert await apply_template(bot, state) == ["description outcome unknown: network"]
