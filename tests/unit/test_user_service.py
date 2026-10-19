"""Unit tests for UserService."""

from unittest.mock import AsyncMock, patch

import pytest
from app.core.exceptions import UserNotFoundException
from app.db.models import User
from app.db.repositories.user import UserRepository
from app.moderation.user_service import UserService

from tests.factories import UserFactory

LOGGER_PATCH_PATH = "app.moderation.user_service.logger"


# --- Module-level fixtures (shared by all test classes) ---


@pytest.fixture
def mock_user_repository() -> AsyncMock:
    """Create a mock user repository."""
    return AsyncMock(spec=UserRepository)


@pytest.fixture
def user_service(mock_user_repository: AsyncMock) -> UserService:
    """Create UserService with mocked dependencies."""
    return UserService(mock_user_repository)


class TestUserService:
    """Test cases for UserService."""

    async def test_get_user_by_id_not_found(self, user_service: UserService, mock_user_repository: AsyncMock):
        """Test getting user by ID when user doesn't exist."""
        user_id = 999999999
        mock_user_repository.get_by_id.return_value = None

        with pytest.raises(UserNotFoundException) as exc_info:
            await user_service.get_user_by_id(user_id)

        assert exc_info.value.user_id == user_id

    async def test_get_user_by_id_optional_not_found(self, user_service: UserService, mock_user_repository: AsyncMock):
        """Test getting user by ID (optional) when user doesn't exist."""
        user_id = 999999999
        mock_user_repository.get_by_id.return_value = None

        result = await user_service.get_user_by_id_optional(user_id)

        assert result is None

    async def test_create_or_update_user_existing_user(self, mock_user_repository: AsyncMock):
        """Test updating an existing user (verifies branch, not log string)."""
        user_id = 123456789
        existing_user = UserFactory.create(id=user_id, username="oldusername", first_name="Old", last_name="Name")

        updated_user = UserFactory.create(id=user_id, username="newusername", first_name="New", last_name="Name")

        mock_user_repository.get_by_id.return_value = existing_user
        mock_user_repository.save.return_value = updated_user

        with patch(LOGGER_PATCH_PATH):
            service = UserService(mock_user_repository)
            result = await service.create_or_update_user(
                user_id=user_id, username="newusername", first_name="New", last_name="Name"
            )

        assert result.username == "newusername"
        assert result.first_name == "New"
        mock_user_repository.save.assert_called_once()


@pytest.mark.unit
class TestUserServiceEdgeCases:
    """Test edge cases and error conditions for UserService."""

    async def test_create_or_update_user_partial_data(self, user_service: UserService, mock_user_repository: AsyncMock):
        """Test creating user with partial data (some None values)."""
        user_id = 123456789
        mock_user_repository.get_by_id.return_value = None
        expected_user = User(id=user_id, username=None, first_name="Test", last_name=None, verify=False, blocked=False)
        mock_user_repository.save.return_value = expected_user

        with patch(LOGGER_PATCH_PATH):
            result = await user_service.create_or_update_user(
                user_id=user_id, username=None, first_name="Test", last_name=None
            )

        assert result.id == user_id
        assert result.username is None
        assert result.first_name == "Test"
        assert result.last_name is None
