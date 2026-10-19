"""Commands that act on a message rather than on a member.

Everything here is a reply-driven Bot API call: the target is whatever the admin
replied to. Each has a refusal path when there is nothing to act on, because a
command that silently does nothing is worse than one that says why.
"""

from unittest.mock import AsyncMock

import pytest
from app.presentation.telegram.handlers.moderation import (
    delete_message,
    kick_user,
    pin_message,
    purge_messages,
    unpin_message,
    user_info,
)

from tests.telegram_helpers import (
    MockBot,
    TelegramObjectFactory,
    create_admin_user,
    create_normal_user,
    create_test_chat,
    no_moderators,
)

pytestmark = pytest.mark.handlers


@pytest.fixture
def telegram_factory():
    return TelegramObjectFactory()


@pytest.fixture
def mock_bot():
    bot = MockBot()
    bot.mock.ban_chat_member = AsyncMock()
    bot.mock.unban_chat_member = AsyncMock()
    bot.mock.delete_message = AsyncMock()
    bot.mock.delete_messages = AsyncMock()
    bot.mock.pin_chat_message = AsyncMock()
    bot.mock.unpin_chat_message = AsyncMock()
    return bot


def _pair(factory: TelegramObjectFactory, command: str, *, reply: bool = True, target_id: int = 777):
    chat = create_test_chat()
    target = create_normal_user(id=target_id, username="offender")
    replied = factory.create_message(user=target, chat=chat) if reply else None
    cmd = factory.create_command_message(command=command, user=create_admin_user(), chat=chat, reply_to_message=replied)
    cmd.answer = AsyncMock()
    cmd.delete = AsyncMock()
    return cmd, replied, chat, target


class TestKick:
    async def test_kick_removes_without_a_lasting_ban(self, telegram_factory, mock_bot, audit_db) -> None:
        """Ban then immediately lift it: gone, but free to come back."""
        cmd, _replied, chat, target = _pair(telegram_factory, "kick")

        await kick_user(cmd, mock_bot.mock, audit_db, no_moderators())

        mock_bot.mock.ban_chat_member.assert_awaited_once_with(chat.id, target.id)
        mock_bot.mock.unban_chat_member.assert_awaited_once_with(chat.id, target.id, only_if_banned=True)

    async def test_kick_is_recorded_against_the_admin_who_asked(self, telegram_factory, mock_bot, audit_db) -> None:
        cmd, _replied, chat, target = _pair(telegram_factory, "kick")

        await kick_user(cmd, mock_bot.mock, audit_db, no_moderators())

        (event,) = audit_db.added
        assert (event.action, event.source) == ("kick", "command")
        assert event.actor_id == cmd.from_user.id
        assert (event.target_user_id, event.chat_id) == (target.id, chat.id)

    async def test_kick_without_a_reply_explains_itself(self, telegram_factory, mock_bot, audit_db) -> None:
        cmd, *_ = _pair(telegram_factory, "kick", reply=False)

        await kick_user(cmd, mock_bot.mock, audit_db, no_moderators())

        cmd.answer.assert_awaited_once()
        mock_bot.mock.ban_chat_member.assert_not_awaited()
        assert audit_db.added == []


class TestDelete:
    async def test_delete_removes_the_replied_message(self, telegram_factory, mock_bot) -> None:
        cmd, replied, chat, _ = _pair(telegram_factory, "del")

        await delete_message(cmd, mock_bot.mock)

        mock_bot.mock.delete_message.assert_awaited_once_with(chat.id, replied.message_id)

    async def test_delete_without_a_reply_explains_itself(self, telegram_factory, mock_bot) -> None:
        cmd, *_ = _pair(telegram_factory, "del", reply=False)

        await delete_message(cmd, mock_bot.mock)

        cmd.answer.assert_awaited_once()
        mock_bot.mock.delete_message.assert_not_awaited()


class TestPurge:
    async def test_purge_clears_the_span_it_was_given(self, telegram_factory, mock_bot) -> None:
        cmd, replied, chat, _ = _pair(telegram_factory, "purge")
        replied.message_id = 100
        cmd.message_id = 105

        await purge_messages(cmd, mock_bot.mock)

        ids = mock_bot.mock.delete_messages.await_args.args[1]
        assert ids == list(range(100, 106))

    async def test_purge_refuses_a_span_it_cannot_bound(self, telegram_factory, mock_bot) -> None:
        """A reply reaching thousands of messages back is a mistake, not a request."""
        cmd, replied, _chat, _ = _pair(telegram_factory, "purge")
        replied.message_id = 1
        cmd.message_id = 5000

        await purge_messages(cmd, mock_bot.mock)

        cmd.answer.assert_awaited_once()
        mock_bot.mock.delete_messages.assert_not_awaited()

    async def test_purge_without_a_reply_explains_itself(self, telegram_factory, mock_bot) -> None:
        cmd, *_ = _pair(telegram_factory, "purge", reply=False)

        await purge_messages(cmd, mock_bot.mock)

        cmd.answer.assert_awaited_once()
        mock_bot.mock.delete_messages.assert_not_awaited()


class TestPin:
    async def test_pin_is_quiet_by_default(self, telegram_factory, mock_bot) -> None:
        """Pinning notifies every member unless told otherwise."""
        cmd, replied, chat, _ = _pair(telegram_factory, "pin")

        await pin_message(cmd, mock_bot.mock)

        mock_bot.mock.pin_chat_message.assert_awaited_once_with(
            chat_id=chat.id, message_id=replied.message_id, disable_notification=True
        )

    async def test_unpin_targets_the_replied_message(self, telegram_factory, mock_bot) -> None:
        cmd, replied, chat, _ = _pair(telegram_factory, "unpin")

        await unpin_message(cmd, mock_bot.mock)

        mock_bot.mock.unpin_chat_message.assert_awaited_once_with(chat_id=chat.id, message_id=replied.message_id)


class TestInfo:
    async def test_info_reports_the_replied_user(self, session, telegram_factory, mock_bot) -> None:
        cmd, _replied, _chat, target = _pair(telegram_factory, "info")

        await user_info(cmd, session)

        cmd.answer.assert_awaited_once()
        assert str(target.id) in cmd.answer.await_args.args[0]

    async def test_info_flags_a_blacklisted_user(self, session, telegram_factory, mock_bot) -> None:
        from app.db.models import User as DbUser

        cmd, _replied, _chat, target = _pair(telegram_factory, "info")
        blocked = DbUser(id=target.id, username="offender")
        blocked.blocked = True
        session.add(blocked)
        await session.commit()

        await user_info(cmd, session)

        assert "чёрн" in cmd.answer.await_args.args[0].lower()

    async def test_info_without_a_reply_explains_itself(self, session, telegram_factory, mock_bot) -> None:
        cmd, *_ = _pair(telegram_factory, "info", reply=False)

        await user_info(cmd, session)

        cmd.answer.assert_awaited_once()
