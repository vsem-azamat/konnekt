"""Telegram testing helpers for simulating bot events and messages."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUnion,
    ChatMemberUpdated,
    Message,
    MessageEntity,
    Update,
    User,
)


class TelegramObjectFactory:
    """Factory for creating Telegram API objects for testing."""

    @staticmethod
    def create_user(
        id: int = 123456789,
        is_bot: bool = False,
        first_name: str = "Test",
        last_name: str | None = "User",
        username: str | None = "testuser",
        language_code: str | None = "en",
    ) -> User:
        """Create a mock Telegram User object."""
        return User(
            id=id,
            is_bot=is_bot,
            first_name=first_name,
            last_name=last_name,
            username=username,
            language_code=language_code,
        )

    @staticmethod
    def create_chat(
        id: int = -1001234567890,
        type: str = "supergroup",
        title: str | None = "Test Chat",
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        is_forum: bool | None = False,
    ) -> Chat:
        """Create a mock Telegram Chat object."""
        from aiogram.types import ChatPermissions

        # Default permissions for supergroups
        default_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        return Chat(
            id=id,
            type=type,
            title=title,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_forum=is_forum,
            permissions=default_permissions,
        )

    @staticmethod
    def create_message(
        message_id: int = 42,
        user: User | None = None,
        chat: Chat | None = None,
        date: datetime | None = None,
        text: str | None = "Test message",
        reply_to_message: Any = None,
        entities: list[MessageEntity] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create a mock Telegram Message object."""
        if user is None:
            user = TelegramObjectFactory.create_user()
        if chat is None:
            chat = TelegramObjectFactory.create_chat()
        if date is None:
            date = datetime.now(UTC)

        # Create message data
        message_data = {
            "message_id": message_id,
            "from_user": user,
            "chat": chat,
            "date": date,
            "text": text,
            "reply_to_message": reply_to_message,
            "entities": entities or [],
            "sender_chat": None,
            "forum_topic_created": None,
            "is_topic_message": None,
            "message_thread_id": None,
            **kwargs,
        }

        # Create mock message with proper attributes
        message = MagicMock(spec=Message)
        for key, value in message_data.items():
            setattr(message, key, value)

        # Add common methods
        message.answer = AsyncMock()
        message.answer_media_group = AsyncMock()
        message.reply = AsyncMock()
        message.delete = AsyncMock()
        message.edit_text = AsyncMock()
        message.edit_reply_markup = AsyncMock()

        return message

    @staticmethod
    def create_command_message(
        command: str, args: str = "", user: User | None = None, chat: Chat | None = None, **kwargs: Any
    ) -> Any:
        """Create a message with a bot command."""
        text = f"/{command}"
        if args:
            text += f" {args}"

        # Create command entity
        entities = [MessageEntity(type="bot_command", offset=0, length=len(f"/{command}"))]

        return TelegramObjectFactory.create_message(text=text, user=user, chat=chat, entities=entities, **kwargs)

    @staticmethod
    def create_reply_message(
        text: str,
        replied_user: User | None = None,
        replying_user: User | None = None,
        chat: Chat | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create a message that replies to another message."""
        if replied_user is None:
            replied_user = TelegramObjectFactory.create_user(id=987654321, username="replieduser")

        reply_to_message = TelegramObjectFactory.create_message(user=replied_user, chat=chat, text="Original message")

        return TelegramObjectFactory.create_message(
            text=text, user=replying_user, chat=chat, reply_to_message=reply_to_message, **kwargs
        )

    @staticmethod
    def create_callback_query(
        id: str = "callback_123",
        user: User | None = None,
        message: Any = None,
        data: str | None = "test_callback",
        **kwargs: Any,
    ) -> Any:
        """Create a mock CallbackQuery object."""
        if user is None:
            user = TelegramObjectFactory.create_user()

        callback_query = MagicMock(spec=CallbackQuery)
        callback_query.id = id
        callback_query.from_user = user
        callback_query.message = message
        callback_query.data = data
        callback_query.answer = AsyncMock()
        callback_query.edit_message_text = AsyncMock()
        callback_query.edit_message_reply_markup = AsyncMock()

        for key, value in kwargs.items():
            setattr(callback_query, key, value)

        return callback_query

    @staticmethod
    def create_chat_member_updated(
        chat: Chat | None = None,
        user: User | None = None,
        old_chat_member: ChatMemberUnion | None = None,
        new_chat_member: ChatMemberUnion | None = None,
        date: datetime | None = None,
        **kwargs,
    ) -> ChatMemberUpdated:
        """Create a ChatMemberUpdated event."""
        if chat is None:
            chat = TelegramObjectFactory.create_chat()
        if user is None:
            user = TelegramObjectFactory.create_user()
        if date is None:
            date = datetime.now(UTC)

        # Create default chat members if not provided
        if old_chat_member is None:
            old_chat_member = ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT)
        if new_chat_member is None:
            new_chat_member = ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER)

        return ChatMemberUpdated(
            chat=chat,
            from_user=user,
            date=date,
            old_chat_member=old_chat_member,
            new_chat_member=new_chat_member,
            **kwargs,
        )

    @staticmethod
    def create_update(
        update_id: int = 123456,
        message: Message | None = None,
        callback_query: CallbackQuery | None = None,
        chat_member: ChatMemberUpdated | None = None,
        **kwargs,
    ) -> Update:
        """Create a mock Update object."""
        return Update(
            update_id=update_id, message=message, callback_query=callback_query, chat_member=chat_member, **kwargs
        )


class MockBot:
    """Mock Bot for testing handlers.

    Tech debt: Tests access methods via `mock_bot.mock.restrict_chat_member` etc.
    This two-level indirection (MockBot wrapping AsyncMock(spec=Bot)) exists because
    handler tests pass `mock_bot.mock` as the Bot argument. Ideally this would be a
    single AsyncMock(spec=Bot), but changing it requires updating all handler tests
    that depend on the `.mock` attribute pattern.
    """

    def __init__(self):
        self.mock = AsyncMock(spec=Bot)
        self._setup_methods()

    def _setup_methods(self):
        """Setup common bot methods."""
        self.mock.send_message = AsyncMock()
        self.mock.edit_message_text = AsyncMock()
        self.mock.delete_message = AsyncMock()
        self.mock.restrict_chat_member = AsyncMock()
        self.mock.ban_chat_member = AsyncMock()
        self.mock.unban_chat_member = AsyncMock()
        self.mock.get_chat_member = AsyncMock()
        self.mock.get_chat = AsyncMock()
        self.mock.answer_callback_query = AsyncMock()

    def __getattr__(self, name):
        return getattr(self.mock, name)


class TelegramEventSimulator:
    """Simulator for complex Telegram events and workflows."""

    def __init__(self, bot: MockBot):
        self.bot = bot
        self.factory = TelegramObjectFactory()

    async def simulate_user_join(
        self, user: User | None = None, chat: Chat | None = None, inviter: User | None = None
    ) -> ChatMemberUpdated:
        """Simulate a user joining a chat."""
        if user is None:
            user = self.factory.create_user()
        if chat is None:
            chat = self.factory.create_chat()
        if inviter is None:
            inviter = self.factory.create_user(id=999999999, username="inviter")

        return self.factory.create_chat_member_updated(
            chat=chat,
            user=inviter,
            old_chat_member=ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT),
            new_chat_member=ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER),
        )

    async def simulate_moderation_action(
        self,
        action: str,
        admin: User | None = None,
        target_user: User | None = None,
        chat: Chat | None = None,
        args: str = "",
    ) -> Any:
        """Simulate a moderation command."""
        if admin is None:
            admin = self.factory.create_user(id=888888888, username="admin")
        if target_user is None:
            target_user = self.factory.create_user(id=777777777, username="target")
        if chat is None:
            chat = self.factory.create_chat()

        return self.factory.create_reply_message(
            text=f"/{action} {args}".strip(), replied_user=target_user, replying_user=admin, chat=chat
        )


# Utility functions for common test scenarios
def create_admin_user(id: int = 888888888) -> User:
    """Create a user that should be treated as admin."""
    return TelegramObjectFactory.create_user(id=id, username="admin_user", first_name="Admin", last_name="User")


def create_normal_user(
    # Not 123456789: that is the test environment's super admin, whom
    # moderation commands refuse to act on.
    id: int = 222333444,
    username: str = "normal_user",
    first_name: str = "Normal",
    last_name: str = "User",
    **kwargs,
) -> User:
    """Create a normal user."""
    return TelegramObjectFactory.create_user(
        id=id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        **kwargs,
    )


def create_test_chat(id: int = -1001234567890) -> Chat:
    """Create a test supergroup chat."""
    return TelegramObjectFactory.create_chat(id=id, title="Test Supergroup", type="supergroup")


def no_moderators() -> Any:
    """An admin repository in which nobody moderates any chat."""
    from unittest.mock import AsyncMock

    repo = AsyncMock()
    repo.is_admin_in.return_value = False
    return repo


class RecordingSession:
    """Stands in for AsyncSession where a handler only writes the audit row.

    Keeps what was added so a test can assert on the record itself rather than
    on the fact that some database call happened.
    """

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:  # pragma: no cover - only on a failed write
        pass

    @property
    def recorded_actions(self) -> list[str]:
        return [obj.action for obj in self.added]


# Pytest fixtures for easy use


@pytest.fixture
def audit_db() -> RecordingSession:
    """A session that captures moderation events instead of storing them."""
    return RecordingSession()


@pytest.fixture
def telegram_factory():
    """Provide TelegramObjectFactory for tests."""
    return TelegramObjectFactory()


@pytest.fixture
def mock_bot():
    """Provide MockBot for tests."""
    return MockBot()
