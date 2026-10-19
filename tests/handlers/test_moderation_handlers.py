"""Tests for moderation handlers."""

from unittest.mock import AsyncMock, patch

import pytest
from app.moderation.mute_permissions import MUTED, UNMUTED
from app.presentation.telegram.handlers.moderation import ban_user, mute_user, unban_user, unmute_user

from tests.telegram_helpers import (
    MockBot,
    TelegramObjectFactory,
    create_admin_user,
    create_normal_user,
    create_test_chat,
)


@pytest.fixture
def telegram_factory():
    return TelegramObjectFactory()


@pytest.fixture
def mock_bot():
    return MockBot()


@pytest.mark.handlers
class TestModerationHandlers:
    """Test cases for moderation handlers."""

    async def test_mute_user_default_duration(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Test muting user with default duration (5 minutes)."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user(id=777777777, username="spammer")
        chat = create_test_chat()

        # Create mute command message (reply to target user)
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="mute", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        # Mock bot methods
        mock_bot.mock.restrict_chat_member = AsyncMock()

        # Mock utility functions
        with (
            patch("app.presentation.telegram.handlers.moderation.mute.other.calculate_mute_duration") as mock_calc,
            patch("app.presentation.telegram.handlers.moderation.mute.other.get_user_mention") as mock_mention,
        ):
            # Configure mocks
            mock_duration = AsyncMock()
            mock_duration.until_date = 1234567890
            mock_duration.time = "5"
            mock_duration.unit = "минут"
            mock_duration.formatted_until_date = lambda: "2024-01-01 12:00:00"
            mock_calc.return_value = mock_duration
            mock_mention.return_value = "@spammer"

            # Act
            await mute_user(command_message, mock_bot.mock, audit_db)

        # Assert
        mock_bot.mock.restrict_chat_member.assert_called_once()
        call_args = mock_bot.mock.restrict_chat_member.call_args

        assert call_args[0][0] == chat.id  # chat_id
        assert call_args[0][1] == target_user.id  # user_id
        assert call_args[1]["until_date"] == 1234567890

        reply_message.reply.assert_called_once()
        command_message.delete.assert_called_once()

    async def test_mute_user_custom_duration(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Test muting user with custom duration."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="mute",
            args="10m",  # 10 minutes
            user=admin_user,
            chat=chat,
            reply_to_message=reply_message,
        )

        # Mock bot methods
        mock_bot.mock.restrict_chat_member = AsyncMock()

        # Mock utility functions
        with (
            patch("app.presentation.telegram.handlers.moderation.mute.other.calculate_mute_duration") as mock_calc,
            patch("app.presentation.telegram.handlers.moderation.mute.other.get_user_mention") as mock_mention,
        ):
            # Configure mocks
            mock_duration = AsyncMock()
            mock_duration.until_date = 1234567890
            mock_duration.time = "10"
            mock_duration.unit = "минут"
            mock_duration.formatted_until_date = lambda: "2024-01-01 12:10:00"
            mock_calc.return_value = mock_duration
            mock_mention.return_value = "@user"

            # Act
            await mute_user(command_message, mock_bot.mock, audit_db)

        # Assert
        mock_bot.mock.restrict_chat_member.assert_called_once()
        mock_calc.assert_called_once_with(command_message.text)

    async def test_mute_user_invalid_duration(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Test mute command with invalid duration argument."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="mute",
            args="invalid",  # Invalid duration
            user=admin_user,
            chat=chat,
            reply_to_message=reply_message,
        )

        # Mock utility functions to raise exception
        with (
            patch("app.presentation.telegram.handlers.moderation.mute.other.calculate_mute_duration") as mock_calc,
            patch("app.presentation.telegram.handlers.moderation.mute.other.sleep_and_delete") as mock_sleep,
        ):
            mock_calc.side_effect = ValueError("Invalid duration")
            mock_sleep.return_value = None

            # Act
            await mute_user(command_message, mock_bot.mock, audit_db)

        # Assert - should handle error gracefully
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()
        mock_sleep.assert_called_once()

    async def test_mute_user_telegram_error(self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db):
        """Test mute command when Telegram API fails."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="mute", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        # Mock bot to raise exception
        mock_bot.mock.restrict_chat_member = AsyncMock(side_effect=Exception("API Error"))

        # Mock utility functions
        with patch("app.presentation.telegram.handlers.moderation.mute.other.calculate_mute_duration") as mock_calc:
            mock_duration = AsyncMock()
            mock_duration.until_date = 1234567890
            mock_calc.return_value = mock_duration

            # Act
            await mute_user(command_message, mock_bot.mock, audit_db)

        # Assert - should handle error gracefully
        command_message.answer.assert_called_once()
        error_msg = command_message.answer.call_args[0][0]
        assert "Произошла ошибка" in error_msg

    async def test_unmute_lifts_the_restriction(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Every permission True, the documented way to lift a restriction.

        It used to read `message.chat.permissions`, which no update carries
        since Bot API 7.3, so `!unmute` always answered that the bot was not an
        admin.
        """
        admin_user = create_admin_user()
        target_user = create_normal_user(id=777777777)
        chat = create_test_chat()
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="unmute", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        await unmute_user(command_message, mock_bot.mock, audit_db)

        kwargs = mock_bot.mock.restrict_chat_member.call_args.kwargs
        assert kwargs["chat_id"] == chat.id
        assert kwargs["user_id"] == target_user.id
        assert kwargs["permissions"] == UNMUTED
        assert "размучен" in command_message.answer.call_args[0][0]

    async def test_mute_takes_every_kind_of_message_and_reactions(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Muting names today's fields; `can_send_media_messages` is gone from the API."""
        admin_user = create_admin_user()
        target_user = create_normal_user(id=777777777)
        chat = create_test_chat()
        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="mute", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        await mute_user(command_message, mock_bot.mock, audit_db)

        sent = mock_bot.mock.restrict_chat_member.call_args.kwargs["permissions"]
        assert sent == MUTED
        assert mock_bot.mock.restrict_chat_member.call_args.kwargs["use_independent_chat_permissions"] is True

    async def test_ban_user_success(self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db):
        """Test successful user ban."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="ban", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        # Mock bot methods
        mock_bot.mock.ban_chat_member = AsyncMock()

        # Mock utility functions
        with patch("app.presentation.telegram.handlers.moderation.ban.other.get_user_mention") as mock_mention:
            mock_mention.return_value = "@user"

            # Act
            await ban_user(command_message, mock_bot.mock, audit_db)

        # Assert
        mock_bot.mock.ban_chat_member.assert_called_once_with(chat.id, target_user.id)
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()

    async def test_unban_user_success(self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db):
        """Test successful user unban."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="unban", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        # Mock bot methods
        mock_bot.mock.unban_chat_member = AsyncMock()

        # Mock utility functions
        with patch("app.presentation.telegram.handlers.moderation.ban.other.get_user_mention") as mock_mention:
            mock_mention.return_value = "@user"

            # Act
            await unban_user(command_message, mock_bot.mock, audit_db)

        # Assert
        mock_bot.mock.unban_chat_member.assert_called_once_with(chat.id, target_user.id)
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()


@pytest.mark.handlers
class TestModerationHandlerEdgeCases:
    """Test edge cases for moderation handlers."""

    async def test_moderation_command_no_reply(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Test moderation commands without reply message."""
        # Arrange
        admin_user = create_admin_user()
        chat = create_test_chat()

        command_message = telegram_factory.create_command_message(
            command="mute",
            user=admin_user,
            chat=chat,  # No reply_to_message
        )

        # Act
        await mute_user(command_message, mock_bot.mock, audit_db)

        # Assert
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()
        answer_text = command_message.answer.call_args[0][0]
        assert "ответом" in answer_text.lower()

    async def test_moderation_permission_error(
        self, telegram_factory: TelegramObjectFactory, mock_bot: MockBot, audit_db
    ):
        """Test moderation when bot lacks permissions."""
        # Arrange
        admin_user = create_admin_user()
        target_user = create_normal_user()
        chat = create_test_chat()

        reply_message = telegram_factory.create_message(user=target_user, chat=chat)
        command_message = telegram_factory.create_command_message(
            command="ban", user=admin_user, chat=chat, reply_to_message=reply_message
        )

        # Mock bot to raise permission error
        mock_bot.mock.ban_chat_member = AsyncMock(side_effect=Exception("Not enough rights"))

        # Mock utility functions
        with patch("app.presentation.telegram.handlers.moderation.ban.other.sleep_and_delete") as mock_sleep:
            mock_sleep.return_value = None

            # Act
            await ban_user(command_message, mock_bot.mock, audit_db)

        # Assert
        command_message.answer.assert_called_once()
        command_message.delete.assert_called_once()
        mock_sleep.assert_called_once()
