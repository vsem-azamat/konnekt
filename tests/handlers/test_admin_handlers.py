"""Tests for !admin and !unadmin.

Both commands act on the chat they were sent in, and the tests care mostly about
that: what the handler tells the repository is a chat id, and what it tells the
room afterwards says which chat it meant.
"""

from unittest.mock import AsyncMock

import pytest
from app.db.repositories.admin import AdminRepository
from app.presentation.telegram.handlers.admin import delete_admin, new_admin

from tests.telegram_helpers import (
    RecordingSession,
    TelegramObjectFactory,
    create_admin_user,
    create_normal_user,
    create_test_chat,
)


@pytest.fixture
def telegram_factory():
    return TelegramObjectFactory()


@pytest.fixture
def mock_admin_repository():
    repo = AsyncMock(spec=AdminRepository)
    repo.chats_for.return_value = []
    return repo


@pytest.mark.handlers
class TestGrantingRights:
    async def test_the_grant_names_the_chat_it_was_sent_in(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        admin_user = create_admin_user()
        target_user = create_normal_user(id=777777777, username="new_admin")
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat, text="I want to be admin")
        command_message = telegram_factory.create_command_message(
            command="admin", user=admin_user, chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.grant.return_value = True
        mock_admin_repository.chats_for.return_value = [chat.id]

        await new_admin(command_message, mock_admin_repository, RecordingSession())

        mock_admin_repository.grant.assert_awaited_once_with(target_user.id, chat.id, granted_by=admin_user.id)
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()

        said = command_message.answer.call_args[0][0]
        assert "модератор этого чата" in said
        assert "✅" in said

    async def test_a_second_chat_is_reported_as_a_count(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        """Whoever grants it should see the reach they just widened."""
        chat = create_test_chat()
        target_user = create_normal_user(id=777777777)
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="admin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.grant.return_value = True
        mock_admin_repository.chats_for.return_value = [chat.id, -1001497722835]

        await new_admin(command_message, mock_admin_repository, RecordingSession())

        assert "Всего чатов под модерацией: 2" in command_message.answer.call_args[0][0]

    async def test_granting_twice_says_so_and_does_not_repeat_itself(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        chat = create_test_chat()
        target_user = create_normal_user(id=777777777, username="existing_admin")
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="admin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.grant.return_value = False

        await new_admin(command_message, mock_admin_repository, RecordingSession())

        assert "уже модерирует" in command_message.answer.call_args[0][0]

    async def test_without_a_reply_nothing_is_granted(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        command_message = telegram_factory.create_command_message(
            command="admin",
            user=create_admin_user(),
            chat=create_test_chat(),
            reply_to_message=None,
        )

        await new_admin(command_message, mock_admin_repository, RecordingSession())

        command_message.answer.assert_called_once()
        assert "ответ на сообщение" in command_message.answer.call_args[0][0].lower()
        mock_admin_repository.grant.assert_not_called()


@pytest.mark.handlers
class TestRevokingRights:
    async def test_the_revoke_names_the_chat_it_was_sent_in(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        chat = create_test_chat()
        target_user = create_normal_user(id=777777777, username="admin_to_remove")
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="unadmin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.revoke.return_value = True

        await delete_admin(command_message, mock_admin_repository, RecordingSession())

        mock_admin_repository.revoke.assert_awaited_once_with(target_user.id, chat.id)
        said = command_message.answer.call_args[0][0]
        assert "больше не модерирует этот чат" in said
        assert "❌" in said

    async def test_remaining_chats_are_spelled_out(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        """Taking one chat back is not the same as taking the job away."""
        chat = create_test_chat()
        target_user = create_normal_user(id=777777777)
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="unadmin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.revoke.return_value = True
        mock_admin_repository.chats_for.return_value = [-1001497722835, -1001192822531]

        await delete_admin(command_message, mock_admin_repository, RecordingSession())

        assert "ещё в 2 чатах" in command_message.answer.call_args[0][0]

    async def test_revoking_from_somebody_who_never_had_it(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        chat = create_test_chat()
        target_user = create_normal_user(id=777777777, username="not_admin")
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="unadmin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.revoke.return_value = False

        await delete_admin(command_message, mock_admin_repository, RecordingSession())

        assert "и так не модерирует" in command_message.answer.call_args[0][0]


@pytest.mark.handlers
class TestWhenTheDatabaseIsDown:
    async def test_the_failure_is_not_swallowed(
        self, telegram_factory: TelegramObjectFactory, mock_admin_repository: AsyncMock
    ):
        """A grant that silently did nothing would be worse than a visible error."""
        chat = create_test_chat()
        reply_message = telegram_factory.create_message(user=create_normal_user(), chat=chat)
        command_message = telegram_factory.create_command_message(
            command="admin", user=create_admin_user(), chat=chat, reply_to_message=reply_message
        )
        mock_admin_repository.grant.side_effect = Exception("Database connection failed")

        with pytest.raises(Exception, match="Database connection failed"):
            await new_admin(command_message, mock_admin_repository, RecordingSession())
