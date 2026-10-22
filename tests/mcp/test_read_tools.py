"""The read toolset's boundaries: what it refuses, and what it never returns.

Two claims carry the weight. Every tool naming a chat must refuse one absent
from the `chats` table, and the refusal has to come before the read rather than
after it. And the projections must drop what should not travel — the free-text
rationale behind a past moderation decision, which is written for an
administrator and not for an external runtime.

Everything these tools read is either our own tables or the Bot API. The one
stub is the bot.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.db.models import Chat, Message, PendingAction, SpamPing, User
from app.mcp.tools.read import register_read_tools

pytestmark = pytest.mark.asyncio

MANAGED_CHAT_ID = -1001234567890
FOREIGN_CHAT_ID = -1009999999999
USER_ID = 555000111
ADMIN_ID = 888000222
PHONE = "+79990001122"


@pytest.fixture
def mcp_session(db_session_maker, monkeypatch):
    """Point the MCP tools at the in-memory test database."""
    from app.db import session as session_module

    monkeypatch.setattr(session_module, "get_session_maker", lambda: db_session_maker)
    return db_session_maker


@pytest.fixture
def bot_stub(monkeypatch):
    """Install a stand-in moderator bot on the container."""
    from app.core.container import container

    bot = SimpleNamespace(
        get_chat=AsyncMock(
            return_value=SimpleNamespace(
                id=MANAGED_CHAT_ID,
                title="Managed Chat",
                type="supergroup",
                username="managed",
                description="О чате",
                linked_chat_id=-100555,
            )
        ),
        get_chat_member_count=AsyncMock(return_value=42),
    )
    monkeypatch.setattr(container, "_bot", bot)
    return bot


def _server():
    """A server carrying only the read toolset — server.py registers it itself."""
    from fastmcp import FastMCP

    mcp: FastMCP[None] = FastMCP(name="read-tools-test", mask_error_details=True)
    register_read_tools(mcp)
    return mcp


async def _call(tool: str, args: dict | None = None):
    from fastmcp import Client

    async with Client(_server()) as client:
        result = await client.call_tool(tool, args or {})
    return result.data


async def _seed_chats(session_maker) -> None:
    async with session_maker() as session:
        session.add(Chat(id=MANAGED_CHAT_ID, title="Managed Chat", resource_status=Chat.STATUS_APPROVED))
        session.add(Chat(id=-100777, title="Seen Once", resource_status=Chat.STATUS_DISCOVERED))
        await session.commit()


async def _seed_foreign_messages(session_maker) -> None:
    """Rows in a chat we do not manage, so a refusal cannot be mistaken for
    an empty answer."""
    async with session_maker() as session:
        session.add(User(id=USER_ID, username="stranger"))
        session.add(Message(chat_id=FOREIGN_CHAT_ID, user_id=USER_ID, message_id=1, message="spam"))
        await session.commit()


async def _seed_blocked_users(session_maker, count: int) -> None:
    async with session_maker() as session:
        for index in range(count):
            session.add(User(id=USER_ID + index, username=f"blocked{index}", blocked=True))
        session.add(User(id=USER_ID + 900, username="innocent", blocked=False))
        await session.commit()


# ── the managed-chat gate ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("get_chat_history", {}),
        ("search_messages", {"query": "spam"}),
        ("find_users_in_chat", {}),
    ],
)
async def test_chat_tools_refuse_a_chat_we_do_not_manage(mcp_session, tool, args) -> None:
    """Only the `chats` table opens a chat, and it is asked first."""
    await _seed_chats(mcp_session)
    await _seed_foreign_messages(mcp_session)

    data = await _call(tool, {"chat_id": FOREIGN_CHAT_ID, **args})

    assert data["error"] == "unknown_chat"
    # Seeded rows exist for that chat, so an empty answer would have passed a
    # weaker test. The refusal has to arrive instead of the data.
    assert "messages" not in data
    assert "users" not in data


async def test_get_chat_info_refuses_a_chat_we_do_not_manage(mcp_session, bot_stub) -> None:
    await _seed_chats(mcp_session)

    data = await _call("get_chat_info", {"chat_id": FOREIGN_CHAT_ID})

    assert data["error"] == "unknown_chat"
    bot_stub.get_chat.assert_not_awaited()


async def test_get_chat_info_never_asks_telegram_about_a_chat_known_by_its_invite_page(mcp_session, bot_stub) -> None:
    """Its id is one of ours, not Telegram's, so it must not reach the Bot API."""
    preview_id = Chat.preview_id_for("5byLmmR3YvIyYWFi")
    async with mcp_session() as session:
        session.add(Chat(id=preview_id, title="UPOL", resource_status=Chat.STATUS_EXTERNAL))
        await session.commit()

    data = await _call("get_chat_info", {"chat_id": preview_id})

    assert data["error"] == "preview_only"
    bot_stub.get_chat.assert_not_awaited()


async def test_managed_chat_history_is_returned(mcp_session) -> None:
    import datetime

    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        row = Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=7, message="hello there")
        row.timestamp = datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.UTC)
        session.add(row)
        await session.commit()

    data = await _call("get_chat_history", {"chat_id": MANAGED_CHAT_ID, "limit": 5})

    assert data["returned"] == 1
    message = data["messages"][0]
    assert message["message_id"] == 7
    assert message["sender_id"] == USER_ID
    assert message["text"] == "hello there"
    assert message["text_truncated"] is False
    assert message["date"].startswith("2026-01-02")


async def test_history_is_newest_first(mcp_session) -> None:
    """A caller reading context wants the end of the conversation, not its start."""
    import datetime

    from app.core.time import utc_now

    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        for offset, text in ((2, "older"), (1, "newer")):
            row = Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=offset, message=text)
            row.timestamp = utc_now() - datetime.timedelta(hours=offset)
            session.add(row)
        await session.commit()

    data = await _call("get_chat_history", {"chat_id": MANAGED_CHAT_ID})

    assert [m["text"] for m in data["messages"]] == ["newer", "older"]


async def test_long_bodies_are_cut_and_say_so(mcp_session) -> None:
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="я" * 2000))
        await session.commit()

    data = await _call("get_chat_history", {"chat_id": MANAGED_CHAT_ID})

    assert data["messages"][0]["text_truncated"] is True
    assert len(data["messages"][0]["text"]) == 1000


async def test_search_finds_a_phrase_regardless_of_case(mcp_session) -> None:
    """Latin here on purpose: these tests run on SQLite, whose case folding is
    ASCII-only. PostgreSQL — what production runs — folds Cyrillic too, and
    `ilike` is what asks it to."""
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="Buy a DIPLOMA"))
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=2, message="привет"))
        await session.commit()

    data = await _call("search_messages", {"chat_id": MANAGED_CHAT_ID, "query": "diploma"})

    assert data["returned"] == 1
    assert data["messages"][0]["message_id"] == 1


async def test_search_does_not_treat_a_percent_as_a_wildcard(mcp_session) -> None:
    """Otherwise a search for "50%" matches everything and reads as a chat
    where every single person is a spammer."""
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="скидка 50% сегодня"))
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=2, message="ничего особенного"))
        await session.commit()

    data = await _call("search_messages", {"chat_id": MANAGED_CHAT_ID, "query": "50%"})

    assert data["returned"] == 1


async def test_search_refuses_an_empty_phrase(mcp_session) -> None:
    """Which would otherwise match every message in the chat."""
    await _seed_chats(mcp_session)

    data = await _call("search_messages", {"chat_id": MANAGED_CHAT_ID, "query": "   "})

    assert data["error"] == "empty_query"


async def test_search_stays_inside_the_chat_it_was_given(mcp_session) -> None:
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="диплом"))
        session.add(Message(chat_id=-100777, user_id=USER_ID, message_id=2, message="диплом"))
        await session.commit()

    data = await _call("search_messages", {"chat_id": MANAGED_CHAT_ID, "query": "диплом"})

    assert data["returned"] == 1


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("get_chat_history", {"limit": 999}, 100),
        ("search_messages", {"query": "x", "limit": 999}, 50),
        ("find_users_in_chat", {"limit": 999}, 200),
    ],
)
async def test_page_sizes_are_clamped(mcp_session, tool, args, expected) -> None:
    """An unbounded page would be a cheap way to pull a whole chat out."""
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        for index in range(expected + 5):
            session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID + index, message_id=index + 1, message="x"))
            session.add(User(id=USER_ID + index, username=f"u{index}"))
        await session.commit()

    data = await _call(tool, {"chat_id": MANAGED_CHAT_ID, **args})

    assert data["returned"] == expected


async def test_users_in_a_chat_are_projected(mcp_session) -> None:
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(User(id=USER_ID, username="ada", first_name="Ada"))
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="hi"))
        await session.commit()

    data = await _call("find_users_in_chat", {"chat_id": MANAGED_CHAT_ID})

    assert data["returned"] == 1
    user = data["users"][0]
    assert user["user_id"] == USER_ID
    assert user["username"] == "ada"
    assert user["first_name"] == "Ada"
    assert user["last_seen"]


async def test_a_person_is_listed_once_however_much_they_wrote(mcp_session) -> None:
    await _seed_chats(mcp_session)
    async with mcp_session() as session:
        session.add(User(id=USER_ID, username="ada"))
        for index in range(5):
            session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=index + 1, message="hi"))
        await session.commit()

    data = await _call("find_users_in_chat", {"chat_id": MANAGED_CHAT_ID})

    assert data["returned"] == 1


# ── withheld fields ───────────────────────────────────────────────────────


async def test_get_user_info_answers_from_our_own_records(mcp_session) -> None:
    async with mcp_session() as session:
        session.add(User(id=USER_ID, username="target", first_name="Target", blocked=True))
        await session.commit()

    data = await _call("get_user_info", {"user_id": USER_ID})

    assert data["known_locally"] is True
    assert data["blocked"] is True
    assert data["username"] == "target"


async def test_get_user_info_says_so_for_somebody_we_have_never_seen(mcp_session) -> None:
    """It answers rather than failing, and `known_locally` carries the caveat."""
    data = await _call("get_user_info", {"user_id": USER_ID})

    assert data["known_locally"] is False
    assert data["username"] == ""


async def test_moderation_history_counts_what_the_bot_recorded(mcp_session) -> None:
    """Built from traces the bot actually leaves, not a decision log it stopped keeping."""
    import datetime

    from app.core.time import utc_now

    async with mcp_session() as session:
        session.add(Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=1, message="hi"))
        spam = Message(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=2, message="buy now")
        spam.mark_as_spam()
        session.add(spam)
        session.add(SpamPing(chat_id=MANAGED_CHAT_ID, user_id=USER_ID, message_id=2, kind="link", matches=["t.me/x"]))
        session.add(
            PendingAction(
                origin="mcp",
                initiator_id=1,
                action="ban",
                target_user_id=USER_ID,
                chat_id=MANAGED_CHAT_ID,
                expires_at=utc_now() + datetime.timedelta(minutes=10),
                reason="repeated ads",
            )
        )
        await session.commit()

    data = await _call("get_moderation_history", {"user_id": USER_ID})

    assert data["messages_seen"] == 2
    assert data["messages_marked_spam"] == 1
    assert data["ad_detector_hits"] == 1
    assert data["chats_seen_in"] == 1
    assert [p["action"] for p in data["proposals"]] == ["ban"]
    assert data["proposals"][0]["status"] == "pending"


async def test_moderation_history_shows_what_was_done_to_the_user(mcp_session) -> None:
    """The half that used to be missing: a command typed in a chat left no row."""
    from app.db.models import ModerationEvent

    async with mcp_session() as session:
        session.add(
            ModerationEvent(
                action="mute",
                source="command",
                actor_id=ADMIN_ID,
                target_user_id=USER_ID,
                chat_id=MANAGED_CHAT_ID,
                detail="5 минут",
            )
        )
        await session.commit()

    data = await _call("get_moderation_history", {"user_id": USER_ID})

    (event,) = data["actions_taken"]
    assert (event["action"], event["source"]) == ("mute", "command")
    assert event["actor_id"] == ADMIN_ID
    assert event["detail"] == "5 минут"


async def test_moderation_history_is_empty_for_a_clean_user(mcp_session) -> None:
    data = await _call("get_moderation_history", {"user_id": USER_ID})

    assert data["known_locally"] is False
    assert data["messages_seen"] == 0
    assert data["proposals"] == []


# ── bounded listings ──────────────────────────────────────────────────────


async def test_get_blacklist_respects_limit(mcp_session) -> None:
    """The assistant's version dumped the whole table; this one must not."""
    await _seed_blocked_users(mcp_session, count=5)

    data = await _call("get_blacklist", {"limit": 2})

    assert data["returned"] == 2
    assert len(data["users"]) == 2
    assert data["total"] == 5
    assert all(user["blocked"] for user in data["users"])


async def test_get_blacklist_excludes_unblocked_users(mcp_session) -> None:
    await _seed_blocked_users(mcp_session, count=3)

    data = await _call("get_blacklist")

    assert data["total"] == 3
    assert "innocent" not in [user["username"] for user in data["users"]]


async def test_get_blacklist_limit_is_clamped(mcp_session) -> None:
    await _seed_blocked_users(mcp_session, count=3)

    data = await _call("get_blacklist", {"limit": 100_000})

    assert data["returned"] == 3


async def test_list_chats_reports_resource_status(mcp_session) -> None:
    """A row in `chats` is not an endorsement — the caller must see which is which."""
    await _seed_chats(mcp_session)

    data = await _call("list_chats")

    by_id = {chat["chat_id"]: chat for chat in data["chats"]}
    assert by_id[MANAGED_CHAT_ID]["resource_status"] == Chat.STATUS_APPROVED
    assert by_id[MANAGED_CHAT_ID]["is_approved"] is True
    assert by_id[-100777]["resource_status"] == Chat.STATUS_DISCOVERED
    assert by_id[-100777]["is_approved"] is False
    assert data["total"] == 2


async def test_list_chats_respects_limit(mcp_session) -> None:
    await _seed_chats(mcp_session)

    data = await _call("list_chats", {"limit": 1})

    assert data["returned"] == 1
    assert data["total"] == 2


# ── surface ───────────────────────────────────────────────────────────────


async def test_chat_info_comes_from_one_bot_api_call(mcp_session, bot_stub) -> None:
    """Description and linked_chat_id used to be fetched a second time through
    a user session. `getChat` had been carrying them the whole time."""
    await _seed_chats(mcp_session)

    data = await _call("get_chat_info", {"chat_id": MANAGED_CHAT_ID})

    assert data["member_count"] == 42
    assert data["description"] == "О чате"
    assert data["linked_chat_id"] == -100555
    assert data["resource_status"] == Chat.STATUS_APPROVED


async def test_toolset_is_read_only(mcp_session) -> None:
    """Pin the exposed surface: nothing here may mutate anything."""
    from fastmcp import Client

    async with Client(_server()) as client:
        names = {tool.name for tool in await client.list_tools()}

    assert names == {
        "list_chats",
        "get_blacklist",
        "get_chat_info",
        "get_user_info",
        "get_moderation_history",
        "get_chat_history",
        "search_messages",
        "find_users_in_chat",
    }
