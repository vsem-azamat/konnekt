"""What a leaked MCP token can and cannot do.

The bounded writes act on the call; the removals only ever queue a request for
a human. These tests are the boundary, since the boundary is no longer "which
tools exist".
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import settings
from app.core.enums import PendingActionStatus
from app.db.models import Chat, PendingAction, User
from app.mcp.server import build_mcp_server
from app.moderation.mute_permissions import MUTED, UNMUTED
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

CHAT_ID = -1001234
UNMANAGED_CHAT_ID = -1009999
USER_ID = 4242
ADMIN_ID = 555


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.restrict_chat_member = AsyncMock()
    tg_bot.unban_chat_member = AsyncMock()
    tg_bot.ban_chat_member = AsyncMock()
    tg_bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    return tg_bot


@pytest.fixture
def wired(db_session_maker, monkeypatch, bot):
    """Point the tools at the test database and a fake moderator bot."""
    from app.core import container as container_module
    from app.db import session as session_module

    monkeypatch.setattr(session_module, "get_session_maker", lambda: db_session_maker)
    monkeypatch.setattr(container_module.container, "try_get_bot", lambda: bot)
    monkeypatch.setattr(settings.admin, "super_admins", [ADMIN_ID])
    return db_session_maker


async def _seed_chat(session_maker) -> None:
    async with session_maker() as session:
        session.add(Chat(id=CHAT_ID, title="Managed", resource_status=Chat.STATUS_APPROVED))
        await session.commit()


async def _call(tool: str, args: dict | None = None):
    from fastmcp import Client

    async with Client(build_mcp_server()) as client:
        return (await client.call_tool(tool, args or {})).data


class TestChatScope:
    async def test_mute_refuses_an_unmanaged_chat(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("mute_user", {"chat_id": UNMANAGED_CHAT_ID, "user_id": USER_ID})

        assert result["error"] == "unknown_chat"
        bot.restrict_chat_member.assert_not_awaited()

    async def test_proposing_a_ban_refuses_an_unmanaged_chat(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("propose_ban", {"chat_id": UNMANAGED_CHAT_ID, "user_id": USER_ID})

        assert result["error"] == "unknown_chat"
        bot.send_message.assert_not_awaited()

    @pytest.mark.parametrize(
        "status", [Chat.STATUS_DISCOVERED, Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL, Chat.STATUS_DISABLED]
    )
    async def test_no_public_action_in_a_chat_awaiting_approval(self, wired, bot, status) -> None:
        """Reading an unapproved chat is fine; acting in one is not.

        Being in the chats table is enough to look, not enough to act — the
        same line the approval gate draws for updates arriving from Telegram.
        """
        async with wired() as session:
            session.add(Chat(id=CHAT_ID, title="Not yet ours", resource_status=status))
            await session.commit()

        result = await _call("mute_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        assert result["error"] == "chat_not_approved"
        bot.restrict_chat_member.assert_not_awaited()


class TestBoundedWrites:
    async def test_mute_applies_and_is_clamped(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("mute_user", {"chat_id": CHAT_ID, "user_id": USER_ID, "minutes": 999_999})

        assert result["status"] == "muted"
        assert result["minutes"] == 43200
        bot.restrict_chat_member.assert_awaited_once()

    async def test_mute_also_takes_away_reactions(self, wired, bot) -> None:
        """Bot API 10.0 split reactions out; muting without it leaves them."""
        await _seed_chat(wired)

        await _call("mute_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        permissions = bot.restrict_chat_member.await_args.kwargs["permissions"]
        assert permissions.can_react_to_messages is False

    async def test_mute_is_the_same_mute_as_the_command(self, wired, bot) -> None:
        await _seed_chat(wired)

        await _call("mute_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        kwargs = bot.restrict_chat_member.await_args.kwargs
        assert kwargs["permissions"] == MUTED
        assert kwargs["use_independent_chat_permissions"] is True

    async def test_unmute_lifts_the_restriction(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("unmute_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        assert result["status"] == "unmuted"
        assert bot.restrict_chat_member.await_args.kwargs["permissions"] == UNMUTED

    async def test_unban_restores_access(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("unban_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        assert result["status"] == "unbanned"
        bot.unban_chat_member.assert_awaited_once()

    async def test_unban_never_removes_someone_still_in_the_chat(self, wired, bot) -> None:
        """Without only_if_banned, Telegram's unban kicks a current member."""
        await _seed_chat(wired)

        await _call("unban_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        assert bot.unban_chat_member.await_args.kwargs["only_if_banned"] is True


class TestStandIns:
    async def test_the_channel_stand_in_cannot_be_proposed_for_the_blacklist(self, wired, bot) -> None:
        """It is every channel post at once; a report shows its id as if it were a person."""
        result = await _call("propose_blacklist", {"user_id": 136817688})

        assert result["error"] == "not_a_person"
        bot.send_message.assert_not_awaited()

    async def test_a_ban_of_a_super_admin_is_refused_at_once(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("propose_ban", {"chat_id": CHAT_ID, "user_id": ADMIN_ID})

        assert result["error"] == "protected_user"
        bot.send_message.assert_not_awaited()


class TestRemovalsWait:
    async def test_propose_ban_bans_nobody(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("propose_ban", {"chat_id": CHAT_ID, "user_id": USER_ID, "reason": "spam"})

        assert result["status"] == "awaiting_confirmation"
        bot.ban_chat_member.assert_not_awaited()

        async with wired() as session:
            pending = await session.scalar(select(PendingAction).where(PendingAction.id == result["pending_id"]))
        assert pending is not None
        assert pending.status == PendingActionStatus.PENDING
        assert pending.origin == "mcp"
        assert pending.initiator_id == ADMIN_ID

    async def test_propose_blacklist_blacklists_nobody(self, wired, bot) -> None:
        result = await _call("propose_blacklist", {"user_id": USER_ID})

        assert result["status"] == "awaiting_confirmation"
        async with wired() as session:
            blocked = await session.scalar(select(User).where(User.id == USER_ID))
        assert blocked is None

    async def test_a_super_admin_is_not_proposed_for_the_blacklist(self, wired, bot) -> None:
        """Refused at the proposal, not only at the press: nobody should be asked."""
        result = await _call("propose_blacklist", {"user_id": ADMIN_ID})

        assert result["error"] == "protected_user"
        bot.send_message.assert_not_awaited()

    async def test_proposal_reaches_the_configured_admin(self, wired, bot) -> None:
        await _call("propose_blacklist", {"user_id": USER_ID})

        assert bot.send_message.await_args.kwargs["chat_id"] == ADMIN_ID

    async def test_the_main_admin_is_the_initiator_by_default(self, wired, bot) -> None:
        """Same convention escalations already follow: the first super admin.

        A separate MCP_INITIATOR_ID duplicated that list for a single-admin
        deployment, which is every deployment so far.
        """
        result = await _call("propose_blacklist", {"user_id": USER_ID})

        assert result["status"] == "awaiting_confirmation"
        assert bot.send_message.await_args.kwargs["chat_id"] == ADMIN_ID

    async def test_an_override_still_wins(self, wired, bot, monkeypatch) -> None:
        """Kept for the case where the token should answer to someone else."""
        monkeypatch.setattr(settings.mcp, "initiator_id", 777)

        await _call("propose_blacklist", {"user_id": USER_ID})

        assert bot.send_message.await_args.kwargs["chat_id"] == 777

    async def test_with_no_admins_at_all_nothing_is_proposed(self, wired, bot, monkeypatch) -> None:
        """Attribution is a precondition, not a nice-to-have on a ban."""
        monkeypatch.setattr(settings.admin, "super_admins", [])
        monkeypatch.setattr(settings.mcp, "initiator_id", 0)

        result = await _call("propose_blacklist", {"user_id": USER_ID})

        assert result["error"] == "no_admin_configured"
        bot.send_message.assert_not_awaited()


class TestRemainingWrites:
    @pytest.mark.parametrize("status", [Chat.STATUS_DISCOVERED, Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL])
    async def test_unmute_refuses_an_unapproved_chat(self, wired, bot, status) -> None:
        async with wired() as session:
            session.add(Chat(id=CHAT_ID, title="Pending", resource_status=status))
            await session.commit()

        result = await _call("unmute_user", {"chat_id": CHAT_ID, "user_id": USER_ID})

        assert result["error"] == "chat_not_approved"
        bot.restrict_chat_member.assert_not_awaited()

    async def test_unblacklist_lifts_the_block(self, wired, bot) -> None:
        async with wired() as session:
            blocked = User(id=USER_ID, username="spammer")
            blocked.blocked = True
            session.add(blocked)
            await session.commit()

        result = await _call("unblacklist_user", {"user_id": USER_ID})

        assert result["status"] == "unblacklisted"
        async with wired() as session:
            row = await session.scalar(select(User).where(User.id == USER_ID))
        assert row is not None
        assert row.blocked is False

    async def test_unblacklist_says_so_for_an_unknown_user(self, wired, bot) -> None:
        result = await _call("unblacklist_user", {"user_id": 12345})

        assert result["error"] == "unknown_user"

    async def test_set_welcome_stores_the_text(self, wired, bot) -> None:
        await _seed_chat(wired)

        result = await _call("set_welcome", {"chat_id": CHAT_ID, "message": "Привет!", "enabled": True})

        assert result["status"] == "updated"
        async with wired() as session:
            chat = await session.scalar(select(Chat).where(Chat.id == CHAT_ID))
        assert chat is not None
        assert chat.welcome_message == "Привет!"
        assert chat.is_welcome_enabled is True

    async def test_set_welcome_can_disable_without_losing_the_text(self, wired, bot) -> None:
        """An empty message means "leave the wording, flip the switch"."""
        async with wired() as session:
            session.add(
                Chat(
                    id=CHAT_ID,
                    title="Managed",
                    resource_status=Chat.STATUS_APPROVED,
                    welcome_message="Старое приветствие",
                    is_welcome_enabled=True,
                )
            )
            await session.commit()

        await _call("set_welcome", {"chat_id": CHAT_ID, "enabled": False})

        async with wired() as session:
            chat = await session.scalar(select(Chat).where(Chat.id == CHAT_ID))
        assert chat is not None
        assert chat.welcome_message == "Старое приветствие"
        assert chat.is_welcome_enabled is False

    @pytest.mark.parametrize("status", [Chat.STATUS_DISCOVERED, Chat.STATUS_OBSERVED, Chat.STATUS_EXTERNAL])
    async def test_set_welcome_refuses_an_unapproved_chat(self, wired, bot, status) -> None:
        async with wired() as session:
            session.add(Chat(id=CHAT_ID, title="Pending", resource_status=status))
            await session.commit()

        result = await _call("set_welcome", {"chat_id": CHAT_ID, "message": "Привет"})

        assert result["error"] == "chat_not_approved"
