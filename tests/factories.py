"""Test data factories for creating test objects."""

import random
from datetime import datetime
from typing import Any

from app.db.models import Admin, Chat, ChatLink, Message, User

# Sentinel object for default values in factories
_DEFAULT: Any = object()


class UserFactory:
    """Factory for creating test users."""

    @staticmethod
    def create(
        id: int | None = None,
        username: str | None | Any = _DEFAULT,
        first_name: str | None | Any = _DEFAULT,
        last_name: str | None | Any = _DEFAULT,
        is_verified: bool = True,
        is_blocked: bool = False,
        created_at: datetime | None = None,
        modified_at: datetime | None = None,
    ) -> User:
        """Create a test user ORM model."""
        user = User(
            id=id if id is not None else random.randint(100000000, 999999999),
            username=username if username is not _DEFAULT else f"testuser{random.randint(1000, 9999)}",
            first_name=first_name if first_name is not _DEFAULT else f"Test{random.randint(1, 100)}",
            last_name=last_name if last_name is not _DEFAULT else f"User{random.randint(1, 100)}",
            verify=is_verified,
            blocked=is_blocked,
        )
        if created_at is not None:
            user.created_at = created_at
        if modified_at is not None:
            user.modified_at = modified_at
        return user

    @staticmethod
    def create_blocked(id: int | None = None, **kwargs) -> User:
        """Create a blocked test user."""
        return UserFactory.create(id=id, is_blocked=True, **kwargs)

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[User]:
        """Create multiple test users."""
        return [UserFactory.create(**kwargs) for _ in range(count)]


class ChatFactory:
    """Factory for creating test chats."""

    @staticmethod
    def create(
        id: int | None = None,
        title: str | None = None,
        is_forum: bool = False,
        welcome_message: str | None = None,
        welcome_delete_time: int = 60,
        is_welcome_enabled: bool = False,
        join_mode: str = Chat.JOIN_ADMINS,
        created_at: datetime | None = None,
        modified_at: datetime | None = None,
    ) -> Chat:
        """Create a test chat ORM model."""
        chat = Chat(
            id=id or -random.randint(1000000000000, 9999999999999),
            title=title or f"Test Chat {random.randint(1, 1000)}",
            is_forum=is_forum,
            welcome_message=welcome_message,
            time_delete=welcome_delete_time,
            is_welcome_enabled=is_welcome_enabled,
            join_mode=join_mode,
        )
        if created_at is not None:
            chat.created_at = created_at
        if modified_at is not None:
            chat.modified_at = modified_at
        return chat

    @staticmethod
    def create_with_welcome(message: str = "Welcome to our chat!", delete_time: int = 60, **kwargs) -> Chat:
        """Create a chat with welcome message enabled."""
        return ChatFactory.create(
            welcome_message=message, welcome_delete_time=delete_time, is_welcome_enabled=True, **kwargs
        )

    @staticmethod
    def create_forum(**kwargs) -> Chat:
        """Create a forum chat."""
        return ChatFactory.create(is_forum=True, **kwargs)

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[Chat]:
        """Create multiple test chats."""
        return [ChatFactory.create(**kwargs) for _ in range(count)]


class AdminFactory:
    """Factory for creating test admins."""

    @staticmethod
    def create(
        id: int | None = None,
        is_active: bool = True,
    ) -> Admin:
        """Create a test admin ORM model."""
        return Admin(
            id=id or random.randint(100000000, 999999999),
            state=is_active,
        )

    @staticmethod
    def create_inactive(**kwargs) -> Admin:
        """Create an inactive admin."""
        return AdminFactory.create(is_active=False, **kwargs)

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[Admin]:
        """Create multiple test admins."""
        return [AdminFactory.create(**kwargs) for _ in range(count)]


class MessageFactory:
    """Factory for creating test messages."""

    @staticmethod
    def create(
        id: int | None = None,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_id: int | None = None,
        content: str | None = None,
        metadata: dict | None = None,
        timestamp: datetime | None = None,
        is_spam: bool = False,
    ) -> Message:
        """Create a test message ORM model."""
        msg = Message(
            chat_id=chat_id or -random.randint(1000000000000, 9999999999999),
            user_id=user_id or random.randint(100000000, 999999999),
            message_id=message_id or random.randint(1, 100000),
            message=content or f"Test message {random.randint(1, 1000)}",
            message_info=metadata or {},
            spam=is_spam,
        )
        if id is not None:
            msg.id = id
        if timestamp is not None:
            msg.timestamp = timestamp
        return msg

    @staticmethod
    def create_spam(**kwargs) -> Message:
        """Create a spam message."""
        return MessageFactory.create(is_spam=True, **kwargs)

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[Message]:
        """Create multiple test messages."""
        return [MessageFactory.create(**kwargs) for _ in range(count)]


class ChatLinkFactory:
    """Factory for creating test chat links."""

    @staticmethod
    def create(
        id: int | None = None,
        text: str | None = None,
        link: str | None = None,
        priority: int = 0,
    ) -> ChatLink:
        """Create a test chat link ORM model."""
        random_id = random.randint(1, 1000)
        chat_link = ChatLink(
            text=text or f"Test Chat Link {random_id}",
            link=link or f"https://t.me/testchat{random_id}",
            priority=priority,
        )
        if id is not None:
            chat_link.id = id
        return chat_link

    @staticmethod
    def create_batch(count: int, **kwargs) -> list[ChatLink]:
        """Create multiple test chat links."""
        return [ChatLinkFactory.create(**kwargs) for _ in range(count)]
