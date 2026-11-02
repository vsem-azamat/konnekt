"""The chat audit reports what the bot recorded about each chat against what the project expects.

Project chats drifted apart because nothing ever compared them: the bot held
different rights in different groups and nobody could say which. The audit is a
read-only pass that turns that into a list of findings per chat, so it can be
run again whenever drift is suspected.

It reads the stored state the bot keeps from Telegram's updates and its daily
checks; only `--apply` asks Telegram again, about the chats it is about to change.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.types import ChatMemberAdministrator, User
from app.chats.audit import ChatState, apply_template, audit_chats, inspect_chat
from app.chats.metadata import ChatMetadata
from app.chats.rights import DEFAULT_ADMIN_RIGHTS
from app.db.models import Chat, ChatBotRights
from sqlalchemy import select
from structlog.testing import capture_logs

pytestmark = pytest.mark.asyncio

BOT_ID = 5145935834
CHAT_ID = -1001000000001
SYNCED = datetime.datetime(2026, 11, 2, 8, 0)


def _full_rights() -> dict[str, bool]:
    return {name: bool(value) for name, value in DEFAULT_ADMIN_RIGHTS.model_dump().items() if isinstance(value, bool)}


def _rights(status: str = "administrator", chat_id: int = CHAT_ID, **overrides: bool) -> ChatBotRights:
    rights = {**_full_rights(), **overrides} if status == "administrator" else {}
    return ChatBotRights(chat_id=chat_id, status=status, rights=rights, changed_at=SYNCED, known_at=SYNCED)


def _synced(chat: Chat, *, description: str | None = "Чат студентов FIT", username: str | None = None) -> Chat:
    """A row as the daily `getChat` left it."""
    chat.description, chat.username, chat.last_synced_at = description, username, SYNCED
    return chat


def _row(*, description: str | None = "Чат студентов FIT", username: str | None = None, **overrides) -> Chat:
    overrides.setdefault("public_link", "https://t.me/+abc")
    return _synced(
        Chat(id=CHAT_ID, title=overrides.pop("title", "ČVUT FIT"), **overrides),
        description=description,
        username=username,
    )


def test_a_chat_in_order_has_no_findings() -> None:
    state = inspect_chat(_row(), _rights())

    assert state.findings == ()
    assert state.bot_status == "administrator"
    assert state.link == "https://t.me/+abc"
    assert state.synced_at == SYNCED


def test_a_bot_that_is_only_a_member_is_reported() -> None:
    state = inspect_chat(_row(), _rights("member"))

    assert "bot is not an administrator" in state.findings


def test_missing_rights_are_named() -> None:
    state = inspect_chat(_row(), _rights(can_pin_messages=False, can_delete_messages=False))

    assert state.missing_rights == ("can_delete_messages", "can_pin_messages")
    assert "missing rights: can_delete_messages, can_pin_messages" in state.findings


def test_topic_rights_matter_only_in_forums() -> None:
    rights = _rights(can_manage_topics=False)

    assert inspect_chat(_row(), rights).missing_rights == ()
    assert inspect_chat(_row(is_forum=True), rights).missing_rights == ("can_manage_topics",)


@pytest.mark.parametrize("status", ["left", "kicked"])
def test_a_chat_the_bot_is_not_in_is_reported(status: str) -> None:
    state = inspect_chat(_row(), _rights(status))

    assert state.reachable is False
    assert state.findings == ("bot is not in the chat",)


def test_a_chat_the_hourly_loop_marked_absent_is_reported() -> None:
    row = _row()
    row.bot_absent_at = SYNCED

    state = inspect_chat(row, _rights())

    assert state.reachable is False
    assert state.findings == ("bot is not in the chat",)


def test_a_bot_added_back_since_the_hourly_loop_marked_the_chat_is_in_it() -> None:
    """The bot's own update records its return at once; the mark waits for the next daily ask."""
    row = _row()
    row.bot_absent_at = SYNCED - datetime.timedelta(hours=1)

    state = inspect_chat(row, _rights())

    assert state.reachable is True
    assert state.findings == ()


def test_a_chat_getchat_never_answered_about_is_not_judged() -> None:
    row = _row()
    row.last_synced_at = None

    state = inspect_chat(row, _rights())

    assert state.reachable is False
    assert state.findings == ("not synced yet",)


def test_a_chat_without_any_link_is_reported() -> None:
    state = inspect_chat(_row(public_link=None), _rights())

    assert "no link" in state.findings


def test_a_public_username_is_the_link() -> None:
    state = inspect_chat(_row(username="cvut_fit", public_link=None), _rights())

    assert state.link == "https://t.me/cvut_fit"
    assert state.findings == ()


def test_a_catalogue_link_to_another_username_is_reported() -> None:
    state = inspect_chat(_row(username="cvut_fit", public_link="https://t.me/old_name"), _rights())

    assert "catalogue link differs from the chat's username" in state.findings


async def test_audit_walks_every_chat_from_what_is_stored(session_maker) -> None:
    async with session_maker() as session:
        gone = _synced(Chat(id=CHAT_ID - 1, title="Gone"))
        gone.bot_absent_at = SYNCED
        session.add_all([_row(), gone])
        await session.flush()
        session.add(_rights())
        await session.commit()
    bot = _bot()

    states = await audit_chats(session_maker=session_maker, bot=bot, pause_seconds=0)

    assert {s.chat_id: s.reachable for s in states} == {CHAT_ID: True, CHAT_ID - 1: False}
    bot.get_chat.assert_not_awaited()
    bot.get_chat_member.assert_not_awaited()


def test_tags_omitted_by_telegram_follow_the_pin_right() -> None:
    rights = _rights()
    del rights.rights["can_manage_tags"]

    assert inspect_chat(_row(), rights).missing_rights == ()


def test_the_welcome_messages_right_is_not_required() -> None:
    """Asked for, never used: the bot sends no welcomes, so a chat that never
    granted it lacks nothing. Bot API added it after the bot was in every chat."""
    assert inspect_chat(_row(), _rights(can_send_welcome_messages=False)).missing_rights == ()


def test_a_creator_lacks_nothing_even_in_a_forum() -> None:
    state = inspect_chat(_row(is_forum=True), _rights("creator"))

    assert state.missing_rights == ()
    assert state.findings == ()


def test_a_restricted_bot_is_not_an_administrator() -> None:
    state = inspect_chat(_row(), _rights("restricted"))

    assert state.findings == ("bot is not an administrator",)


def test_rights_never_checked_keep_the_chat_info() -> None:
    state = inspect_chat(_row(), None)

    assert state.reachable is True
    assert state.description == "Чат студентов FIT"
    assert state.findings == ("bot's membership unknown: not checked yet",)


def test_usernames_compare_without_case() -> None:
    state = inspect_chat(_row(username="cvut_fit", public_link="https://t.me/CVUT_FIT"), _rights())

    assert state.findings == ()


def test_a_catalogue_username_the_chat_no_longer_has_is_reported() -> None:
    state = inspect_chat(_row(public_link="https://t.me/old_name"), _rights())

    assert state.findings == ("catalogue links a username the chat no longer has",)


def test_an_invite_link_in_the_catalogue_is_not_a_username() -> None:
    state = inspect_chat(_row(public_link="https://t.me/+abc"), _rights())

    assert state.findings == ()


# --- The template (#155) --------------------------------------------------

BOT_USERNAME = "konnekt_cz_bot"
PARENT = Chat(id=CHAT_ID - 100, title="ČVUT | ЧВУТ", institution_code="cvut", public_link="https://t.me/cvut_chat")


def _university_row(**overrides) -> Chat:
    return _row(resource_status=Chat.STATUS_APPROVED, parent_chat_id=PARENT.id, **overrides)


def _expected(current: str = "Чат студентов FIT") -> str:
    from app.chats.template import expected_description

    return expected_description(title="ČVUT FIT", current=current, bot=BOT_USERNAME, university=True, parent=PARENT)


def _inspect(chat: Chat, rights: ChatBotRights | None = None) -> ChatState:
    return inspect_chat(chat, rights or _rights(), bot_username=BOT_USERNAME, parent=PARENT, university=True)


def _admin_member(**overrides: bool) -> ChatMemberAdministrator:
    bot_user = User(id=BOT_ID, is_bot=True, first_name="Konnekt")
    return ChatMemberAdministrator.model_validate(
        {"user": bot_user, "can_be_edited": False, **{**_full_rights(), **overrides}}
    )


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.id = BOT_ID
    bot.me.return_value = SimpleNamespace(username=BOT_USERNAME)
    bot.get_chat_member.return_value = _admin_member()
    return bot


def test_a_description_off_the_template_is_reported() -> None:
    state = _inspect(_university_row())

    assert state.expected_description == _expected()
    assert state.findings == ("description differs from the template",)


def test_a_description_on_the_template_is_not_reported() -> None:
    state = _inspect(_university_row(description=_expected()))

    assert state.findings == ()


def test_only_approved_chats_are_held_to_the_template() -> None:
    state = _inspect(_row())

    assert state.expected_description is None
    assert state.findings == ()


async def test_apply_sets_the_description() -> None:
    bot = _bot()

    assert await apply_template(bot, _inspect(_university_row())) == ["description set"]
    bot.set_chat_description.assert_awaited_once_with(chat_id=CHAT_ID, description=_expected())


async def test_apply_leaves_a_description_already_on_the_template() -> None:
    bot = _bot()

    assert await apply_template(bot, _inspect(_university_row(description=_expected()))) == []
    bot.set_chat_description.assert_not_awaited()


async def test_apply_does_not_write_an_empty_description_over_none() -> None:
    bot = _bot()
    state = inspect_chat(
        _row(resource_status=Chat.STATUS_APPROVED, description=None), _rights(), bot_username=BOT_USERNAME
    )

    assert state.findings == ()
    assert await apply_template(bot, state) == []
    bot.set_chat_description.assert_not_awaited()


async def test_apply_without_the_right_leaves_the_description() -> None:
    bot = _bot()

    state = _inspect(_university_row(), _rights(can_change_info=False))

    assert await apply_template(bot, state) == ["description: no right to change it"]
    bot.set_chat_description.assert_not_awaited()


async def test_apply_under_flood_control_says_it_did_not_set() -> None:
    bot = _bot()
    bot.set_chat_description.side_effect = TelegramRetryAfter(method=AsyncMock(), message="Too Many", retry_after=0)

    assert await apply_template(bot, _inspect(_university_row())) == ["description not set: flood control"]


async def test_apply_with_unknown_rights_does_not_try() -> None:
    bot = _bot()
    state = inspect_chat(_university_row(), None, bot_username=BOT_USERNAME, parent=PARENT, university=True)

    assert await apply_template(bot, state) == ["description: rights unknown"]
    bot.set_chat_description.assert_not_awaited()


async def test_apply_after_a_network_error_does_not_claim_either_way() -> None:
    bot = _bot()
    bot.set_chat_description.side_effect = TelegramNetworkError(method=AsyncMock(), message="timeout")

    assert await apply_template(bot, _inspect(_university_row())) == ["description outcome unknown: network"]


def test_the_template_uses_the_stored_title() -> None:
    """The title the bot recorded last; every update carries it, so a rename is in by the next message."""
    state = _inspect(_university_row(title="ČVUT FIT"))

    assert state.expected_description == _expected()


# --- The whole table ---------------------------------------------------------

DORMITORY_TEXT = "Чат для живущих в ареале Strahov"


async def _seed_cvut(session_maker, *, description: str = DORMITORY_TEXT) -> None:
    approved = Chat.STATUS_APPROVED
    async with session_maker() as session:
        session.add_all(
            [
                _synced(
                    Chat(
                        id=-1,
                        title="ČVUT | ЧВУТ",
                        institution_code="cvut",
                        resource_status=approved,
                        public_link="https://t.me/+cvut",
                    ),
                    description=description,
                ),
                _synced(
                    Chat(
                        id=-2,
                        title="Strahov",
                        institution_code="cvut",
                        resource_status=approved,
                        public_link="https://t.me/+cvut",
                    ),
                    description=description,
                ),
                _synced(
                    Chat(
                        id=-3,
                        title="ČVUT FIT",
                        parent_chat_id=-1,
                        resource_status=approved,
                        public_link="https://t.me/+fit",
                    ),
                    description=description,
                ),
            ]
        )
        await session.flush()
        session.add_all([_rights(chat_id=chat_id) for chat_id in (-1, -2, -3)])
        await session.commit()


@pytest.fixture
def telegram_now(monkeypatch) -> dict[int, ChatMetadata | None]:
    """What `getChat` answers when `--apply` asks again, by chat; a chat left out is not answered."""
    answers: dict[int, ChatMetadata | None] = {}
    asked = AsyncMock(side_effect=lambda **kwargs: answers.get(kwargs["chat_id"]))
    monkeypatch.setattr("app.chats.audit.fetch_metadata", asked)
    return answers


async def _audit(session_maker, **kwargs):
    bot = _bot()
    return bot, await audit_chats(session_maker=session_maker, bot=bot, pause_seconds=0, **kwargs)


async def test_a_dormitory_keeps_its_text_even_when_audited_alone(session_maker) -> None:
    await _seed_cvut(session_maker)

    _, states = await _audit(session_maker, chat_ids={-2})

    assert [s.expected_description for s in states] == [DORMITORY_TEXT]


async def test_the_university_and_its_faculty_get_the_template(session_maker) -> None:
    await _seed_cvut(session_maker)

    _, states = await _audit(session_maker, chat_ids={-1, -3})

    first_lines = {s.chat_id: (s.expected_description or "").splitlines()[0] for s in states}
    assert first_lines == {
        -1: "🎓 Чат студентов и абитуриентов ČVUT",
        -3: "🎓 Чат студентов и абитуриентов ČVUT FIT",
    }


async def test_a_main_chat_in_its_owners_words_keeps_them(session_maker, monkeypatch) -> None:
    await _seed_cvut(session_maker)
    monkeypatch.setattr("app.chats.audit.OWN_WORDS", frozenset({-1}))

    _, states = await _audit(session_maker, chat_ids={-1})

    assert [s.expected_description for s in states] == [
        DORMITORY_TEXT + "\n\nВсе чаты и помощь с учёбой: @" + BOT_USERNAME
    ]


async def test_own_words_that_do_not_fit_are_a_finding_not_a_change(session_maker, monkeypatch, telegram_now) -> None:
    await _seed_cvut(session_maker, description="X" * 250)
    monkeypatch.setattr("app.chats.audit.OWN_WORDS", frozenset({-1}))

    bot, states = await _audit(session_maker, apply=True, chat_ids={-1})

    assert states[0].findings == ("own words do not fit with the bot line",)
    assert states[0].applied == ()
    bot.set_chat_description.assert_not_awaited()


async def test_an_own_words_id_that_is_not_an_approved_chat_is_reported(session_maker, monkeypatch) -> None:
    await _seed_cvut(session_maker)
    monkeypatch.setattr("app.chats.audit.OWN_WORDS", frozenset({-1, -999}))

    with capture_logs() as logs:
        await _audit(session_maker, chat_ids={-2})

    assert [log["chat_ids"] for log in logs if log["event"] == "own_words_not_approved"] == [[-999]]


async def test_apply_asks_again_and_applies_only_to_the_chats_asked_for(session_maker, telegram_now) -> None:
    await _seed_cvut(session_maker)
    telegram_now[-3] = ChatMetadata(title="ČVUT FIT", photo_file_id=None, description=DORMITORY_TEXT)

    bot, states = await _audit(session_maker, apply=True, chat_ids={-3})

    assert [s.chat_id for s in states] == [-3]
    assert [c.kwargs["chat_id"] for c in bot.set_chat_description.await_args_list] == [-3]
    assert states[0].applied == ("description set",)


async def test_apply_judges_by_what_telegram_says_now_and_records_it(session_maker, telegram_now) -> None:
    """Somebody fixed the description by hand since the daily pass: nothing to write, and the row catches up."""
    await _seed_cvut(session_maker)
    _, [stale] = await _audit(session_maker, chat_ids={-3})
    telegram_now[-3] = ChatMetadata(title="ČVUT FIT", photo_file_id=None, description=stale.expected_description)

    bot, states = await _audit(session_maker, apply=True, chat_ids={-3})

    bot.set_chat_description.assert_not_awaited()
    assert states[0].findings == ()
    assert states[0].applied == ()
    async with session_maker() as session:
        row = (await session.execute(select(Chat).where(Chat.id == -3))).scalar_one()
        assert row.description == stale.expected_description
        assert row.last_synced_at > SYNCED


async def test_apply_writes_nothing_where_telegram_does_not_answer(session_maker, telegram_now) -> None:
    await _seed_cvut(session_maker)

    bot, states = await _audit(session_maker, apply=True, chat_ids={-3})

    bot.set_chat_description.assert_not_awaited()
    assert states[0].applied == ("description not set: Telegram did not answer",)


async def test_the_report_alone_never_asks_telegram(session_maker, telegram_now) -> None:
    await _seed_cvut(session_maker)

    bot, _ = await _audit(session_maker)

    bot.get_chat.assert_not_awaited()
    bot.set_chat_description.assert_not_awaited()


async def test_after_apply_the_report_shows_what_was_written(session_maker, telegram_now) -> None:
    """Telegram sends no update for a new description, and the row was just marked fresh."""
    await _seed_cvut(session_maker)
    telegram_now[-3] = ChatMetadata(title="ČVUT FIT", photo_file_id=None, description=DORMITORY_TEXT)
    _, [applied] = await _audit(session_maker, apply=True, chat_ids={-3})

    _, [after] = await _audit(session_maker, chat_ids={-3})

    assert applied.applied == ("description set",)
    assert after.description == applied.expected_description
    assert after.findings == ()


async def test_apply_asks_for_the_bots_rights_again_before_judging_them(session_maker, telegram_now) -> None:
    """A promotion whose update was lost would otherwise keep the description as it is until the daily check."""
    await _seed_cvut(session_maker)
    async with session_maker() as session:
        (await session.get(ChatBotRights, -3)).rights = {**_full_rights(), "can_change_info": False}
        await session.commit()
    telegram_now[-3] = ChatMetadata(title="ČVUT FIT", photo_file_id=None, description=DORMITORY_TEXT)

    bot, [state] = await _audit(session_maker, apply=True, chat_ids={-3})

    bot.get_chat_member.assert_awaited_once_with(-3, BOT_ID)
    assert state.applied == ("description set",)
    async with session_maker() as session:
        assert (await session.get(ChatBotRights, -3)).rights["can_change_info"] is True
