"""Domain exceptions for the moderation bot."""

# ruff: noqa: N818


class DomainError(Exception):
    """Base domain exception."""

    pass


class UserNotFoundException(DomainError):
    """Raised when user is not found."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(f"User with ID {user_id} not found")


class ProtectedUserError(DomainError):
    """Raised when an action would remove a super admin."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(f"User {user_id} is a super admin and cannot be removed")


class ChatNotManagedError(DomainError):
    """Raised when an action would act in a chat the bot does not moderate."""

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        super().__init__(f"Chat {chat_id} is not one the bot moderates")


class NotAPersonError(DomainError):
    """Raised when an action names one of Telegram's stand-in senders."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(f"{user_id} is Telegram's stand-in for posts no person signed")
