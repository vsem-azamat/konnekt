"""User domain service."""

from app.core.exceptions import UserNotFoundException
from app.core.logging import get_logger
from app.db.models import User
from app.db.repositories.user import UserRepository

logger = get_logger(__name__)


class UserService:
    """User domain service."""

    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def get_user_by_id(self, user_id: int) -> User:
        """Get user by ID, raise exception if not found."""
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise UserNotFoundException(user_id)
        return user

    async def get_user_by_id_optional(self, user_id: int) -> User | None:
        """Get user by ID, return None if not found."""
        return await self.user_repository.get_by_id(user_id)

    async def create_or_update_user(
        self,
        user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Create or update user with profile information."""
        existing_user = await self.user_repository.get_by_id(user_id)

        if existing_user:
            existing_user.username = username
            existing_user.first_name = first_name
            existing_user.last_name = last_name
            user = await self.user_repository.save(existing_user)
            logger.info("profile_updated", user_id=user_id)
        else:
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            user = await self.user_repository.save(user)
            logger.info("user_created", user_id=user_id)

        return user

    async def get_blocked_users(self) -> list[User]:
        """Get all blocked users."""
        return await self.user_repository.get_blocked_users()

    async def find_blocked_user(self, identifier: str) -> User | None:
        """Find blocked user by username or user_id."""
        return await self.user_repository.find_blocked_user(identifier)

    async def is_user_blocked(self, user_id: int) -> bool:
        """Check if user is blocked."""
        user = await self.user_repository.get_by_id(user_id)
        return user.is_blocked if user else False
