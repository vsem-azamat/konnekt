"""User domain service."""

from app.core.logging import get_logger
from app.db.models import User
from app.db.repositories.user import UserRepository

logger = get_logger(__name__)


class UserService:
    """User domain service."""

    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def get_blocked_users(self) -> list[User]:
        """Get all blocked users."""
        return await self.user_repository.get_blocked_users()

    async def find_blocked_user(self, identifier: str) -> User | None:
        """Find blocked user by username or user_id."""
        return await self.user_repository.find_blocked_user(identifier)
