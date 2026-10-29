"""Integration tests for ChatRepository."""

import pytest
from app.db.models import Chat
from app.db.repositories.chat import ChatRepository

from tests.factories import ChatFactory


@pytest.mark.integration
class TestChatRepositoryIntegration:
    """Integration tests for ChatRepository."""

    async def test_save_and_get_chat(self, chat_repository: ChatRepository, sample_chat_data: dict):
        """Test saving and retrieving a chat."""
        # Create chat
        chat = ChatFactory.create(**sample_chat_data)

        # Save chat
        saved_chat = await chat_repository.save(chat)

        # Verify save
        assert saved_chat.id == chat.id
        assert saved_chat.title == chat.title
        assert saved_chat.is_forum == chat.is_forum

        # Retrieve chat
        retrieved_chat = await chat_repository.get_by_id(chat.id)

        # Verify retrieval
        assert retrieved_chat is not None
        assert retrieved_chat.id == chat.id
        assert retrieved_chat.title == chat.title
        assert retrieved_chat.is_forum == chat.is_forum

    async def test_get_nonexistent_chat(self, chat_repository: ChatRepository):
        """Test getting a chat that doesn't exist."""
        nonexistent_id = -999999999999

        chat = await chat_repository.get_by_id(nonexistent_id)

        assert chat is None

    async def test_chat_exists(self, chat_repository: ChatRepository):
        """Test checking if chat exists."""
        chat = ChatFactory.create()

        # Chat doesn't exist yet
        exists_before = await chat_repository.exists(chat.id)
        assert exists_before is False

        # Save chat
        await chat_repository.save(chat)

        # Chat exists now
        exists_after = await chat_repository.exists(chat.id)
        assert exists_after is True

    async def test_update_existing_chat(self, chat_repository: ChatRepository):
        """Test updating an existing chat."""
        # Create and save chat
        chat = ChatFactory.create(title="Original Title", is_forum=False, welcome_message="Original welcome")
        await chat_repository.save(chat)

        # Update chat data
        chat.title = "Updated Title"
        chat.is_forum = True
        chat.welcome_message = "Updated welcome"

        # Save updated chat
        updated_chat = await chat_repository.save(chat)

        # Verify update
        assert updated_chat.title == "Updated Title"
        assert updated_chat.is_forum is True
        assert updated_chat.welcome_message == "Updated welcome"

        # Verify in database
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None
        assert retrieved_chat.title == "Updated Title"
        assert retrieved_chat.is_forum is True
        assert retrieved_chat.welcome_message == "Updated welcome"

    async def test_chat_welcome_settings(self, chat_repository: ChatRepository):
        """Test chat welcome message settings."""
        # Create chat with welcome settings
        chat = ChatFactory.create_with_welcome(message="Welcome to our chat!", delete_time=120)

        saved_chat = await chat_repository.save(chat)

        assert saved_chat.welcome_message == "Welcome to our chat!"
        assert saved_chat.time_delete == 120
        assert saved_chat.is_welcome_enabled is True

        # Retrieve and verify
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None
        assert retrieved_chat.welcome_message == "Welcome to our chat!"
        assert retrieved_chat.time_delete == 120
        assert retrieved_chat.is_welcome_enabled is True

    async def test_forum_chat(self, chat_repository: ChatRepository):
        """Test forum chat functionality."""
        chat = ChatFactory.create_forum(title="Test Forum")

        saved_chat = await chat_repository.save(chat)

        assert saved_chat.is_forum is True
        assert saved_chat.title == "Test Forum"

        # Retrieve and verify
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None
        assert retrieved_chat.is_forum is True

    async def test_get_all_chats_empty(self, chat_repository: ChatRepository):
        """Test getting all chats when none exist."""
        chats = await chat_repository.get_chats()

        assert chats == []

    async def test_get_all_chats_with_data(self, chat_repository: ChatRepository):
        """Test getting all chats with data."""
        # Create and save multiple chats
        chats = ChatFactory.create_batch(3)

        for chat in chats:
            await chat_repository.save(chat)

        # Get all chats
        all_chats = await chat_repository.get_chats()

        # Verify results
        assert len(all_chats) == 3
        chat_ids = {chat.id for chat in all_chats}
        expected_ids = {chat.id for chat in chats}
        assert chat_ids == expected_ids

    async def test_save_chat_with_minimal_data(self, chat_repository: ChatRepository):
        """Test saving chat with minimal required data."""
        chat = Chat(id=-1001234567890)

        saved_chat = await chat_repository.save(chat)

        assert saved_chat.id == -1001234567890
        assert saved_chat.title is None
        assert saved_chat.is_forum is False  # Default
        assert saved_chat.time_delete == 60  # Default
        assert saved_chat.is_welcome_enabled is False  # Default
        assert saved_chat.is_captcha_enabled is False  # Default

    async def test_chat_captcha_settings(self, chat_repository: ChatRepository):
        """Test chat captcha settings."""
        chat = ChatFactory.create(join_mode=Chat.JOIN_CAPTCHA)

        saved_chat = await chat_repository.save(chat)
        assert saved_chat.is_captcha_enabled is True

        # Toggle captcha
        chat.join_mode = Chat.JOIN_ADMINS
        updated_chat = await chat_repository.save(chat)
        assert updated_chat.is_captcha_enabled is False

        # Verify in database
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None
        assert retrieved_chat.is_captcha_enabled is False

    async def test_multiple_chats_different_ids(self, chat_repository: ChatRepository):
        """Test saving multiple chats with different IDs."""
        chats = ChatFactory.create_batch(5)

        # Save all chats
        saved_chats = []
        for chat in chats:
            saved_chat = await chat_repository.save(chat)
            saved_chats.append(saved_chat)

        # Verify all chats were saved
        assert len(saved_chats) == 5

        # Verify all chats can be retrieved
        for original_chat in chats:
            retrieved_chat = await chat_repository.get_by_id(original_chat.id)
            assert retrieved_chat is not None
            assert retrieved_chat.id == original_chat.id

    async def test_chat_settings_persistence(self, chat_repository: ChatRepository):
        """Test that chat settings persist across saves."""
        chat = ChatFactory.create(is_welcome_enabled=False, welcome_delete_time=60)
        await chat_repository.save(chat)

        # Change chat settings
        chat.is_welcome_enabled = True
        chat.join_mode = Chat.JOIN_CAPTCHA
        chat.time_delete = 120
        chat.welcome_message = "New welcome message"

        # Save changes
        await chat_repository.save(chat)

        # Retrieve and verify
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None
        assert retrieved_chat.is_welcome_enabled is True
        assert retrieved_chat.is_captcha_enabled is True
        assert retrieved_chat.time_delete == 120
        assert retrieved_chat.welcome_message == "New welcome message"


@pytest.mark.integration
class TestChatRepositoryEdgeCases:
    """Edge cases and error conditions for ChatRepository."""

    async def test_save_chat_with_duplicate_id(self, chat_repository: ChatRepository):
        """Test saving chats with the same ID (should update)."""
        chat_id = -1001234567890

        # Create first chat
        chat1 = ChatFactory.create(id=chat_id, title="First Chat", is_forum=False)
        await chat_repository.save(chat1)

        # Create second chat with same ID but different data
        chat2 = ChatFactory.create(id=chat_id, title="Second Chat", is_forum=True)
        saved_chat2 = await chat_repository.save(chat2)

        # Should have updated the existing chat
        assert saved_chat2.id == chat_id
        assert saved_chat2.title == "Second Chat"
        assert saved_chat2.is_forum is True

        # Verify only one chat exists in database
        retrieved_chat = await chat_repository.get_by_id(chat_id)
        assert retrieved_chat is not None
        assert retrieved_chat.title == "Second Chat"
        assert retrieved_chat.is_forum is True

    @pytest.mark.skip(reason="SQLAlchemy sessions don't support concurrent operations")
    async def test_concurrent_chat_operations(self, chat_repository: ChatRepository):
        """Test concurrent operations on different chats."""
        import asyncio

        chats = ChatFactory.create_batch(10)

        # Save chats concurrently
        save_tasks = [chat_repository.save(chat) for chat in chats]
        saved_chats = await asyncio.gather(*save_tasks)

        assert len(saved_chats) == 10

        # Retrieve chats concurrently
        retrieve_tasks = [chat_repository.get_by_id(chat.id) for chat in chats]
        retrieved_chats = await asyncio.gather(*retrieve_tasks)

        assert len(retrieved_chats) == 10
        assert all(chat is not None for chat in retrieved_chats)

    async def test_chat_with_very_long_strings(self, chat_repository: ChatRepository):
        """Test chat with very long string values."""
        long_string = "a" * 1000  # Very long string

        chat = ChatFactory.create(
            title=long_string[:200],  # Assuming reasonable DB limits
            welcome_message=long_string[:500],
        )

        saved_chat = await chat_repository.save(chat)

        assert saved_chat.title == long_string[:200]
        assert saved_chat.welcome_message == long_string[:500]

    async def test_chat_with_special_characters(self, chat_repository: ChatRepository):
        """Test chat with special characters in strings."""
        chat = ChatFactory.create(
            title="测试聊天室 🚀",  # Chinese + emoji
            welcome_message="Bienvenido! 欢迎 👋",  # Mixed languages + emoji
        )

        await chat_repository.save(chat)
        retrieved_chat = await chat_repository.get_by_id(chat.id)
        assert retrieved_chat is not None

        assert retrieved_chat.title == "测试聊天室 🚀"
        assert retrieved_chat.welcome_message == "Bienvenido! 欢迎 👋"

    async def test_chat_with_none_values(self, chat_repository: ChatRepository):
        """Test saving chat with explicit None values."""
        chat = Chat(id=-1001234567890, title=None, welcome_message=None)

        saved_chat = await chat_repository.save(chat)

        assert saved_chat.title is None
        assert saved_chat.welcome_message is None

    async def test_chat_welcome_time_boundaries(self, chat_repository: ChatRepository):
        """Test chat welcome delete time boundary values."""
        # Test minimum valid time
        chat1 = ChatFactory.create(welcome_delete_time=1)
        saved_chat1 = await chat_repository.save(chat1)
        assert saved_chat1.time_delete == 1

        # Test large valid time
        chat2 = ChatFactory.create(welcome_delete_time=86400)  # 24 hours
        saved_chat2 = await chat_repository.save(chat2)
        assert saved_chat2.time_delete == 86400

    async def test_positive_and_negative_chat_ids(self, chat_repository: ChatRepository):
        """Test both positive (private) and negative (group/supergroup) chat IDs."""
        # Positive chat ID (private chat - though bot usually doesn't manage these)
        positive_chat = ChatFactory.create(id=123456789)
        saved_positive = await chat_repository.save(positive_chat)
        assert saved_positive.id == 123456789

        # Negative chat ID (group/supergroup)
        negative_chat = ChatFactory.create(id=-1001234567890)
        saved_negative = await chat_repository.save(negative_chat)
        assert saved_negative.id == -1001234567890

        # Both should be retrievable
        retrieved_positive = await chat_repository.get_by_id(123456789)
        retrieved_negative = await chat_repository.get_by_id(-1001234567890)

        assert retrieved_positive is not None
        assert retrieved_negative is not None


@pytest.mark.integration
class TestChatRepositoryLegacy:
    """Tests for legacy backward-compatible methods."""

    async def test_legacy_merge_and_get_chat(self, session):
        """Test legacy merge_chat and get_chat methods."""
        repo = ChatRepository(session)
        await repo.merge_chat(1, title="Test", is_forum=True)
        chat = await repo.get_by_id(1)
        assert chat is not None
        assert chat.title == "Test"
        assert chat.is_forum is True
