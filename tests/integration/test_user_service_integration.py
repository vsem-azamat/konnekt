"""Integration tests for user management service workflows."""

import pytest
from app.db.repositories.user import UserRepository
from app.moderation.user_service import UserService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
class TestUserWorkflowIntegration:
    """Integration tests for complete user workflows."""

    async def test_user_profile_updates_workflow(self, user_repository: UserRepository, session: AsyncSession):
        """Test various user profile update scenarios."""
        user_service = UserService(user_repository)
        user_id = 333333333

        # 1. Create user with minimal info
        user = await user_service.create_or_update_user(user_id=user_id, username="minimal_user")

        assert user.username == "minimal_user"
        assert user.first_name is None
        assert user.last_name is None

        # 2. Add first name
        user = await user_service.create_or_update_user(user_id=user_id, username="minimal_user", first_name="John")

        assert user.first_name == "John"
        assert user.last_name is None

        # 3. Add last name
        user = await user_service.create_or_update_user(
            user_id=user_id, username="minimal_user", first_name="John", last_name="Doe"
        )

        assert user.first_name == "John"
        assert user.last_name == "Doe"

        # 4. Update username
        user = await user_service.create_or_update_user(
            user_id=user_id, username="john_doe", first_name="John", last_name="Doe"
        )

        assert user.username == "john_doe"

        # 5. Clear some fields (set to None)
        user = await user_service.create_or_update_user(
            user_id=user_id, username=None, first_name="John", last_name=None
        )

        assert user.username is None
        assert user.first_name == "John"
        assert user.last_name is None

        # 6. Verify persistence
        retrieved_user = await user_service.get_user_by_id(user_id)
        assert retrieved_user.username is None
        assert retrieved_user.first_name == "John"
        assert retrieved_user.last_name is None


@pytest.mark.integration
class TestUserErrorScenariosIntegration:
    """Test error scenarios in user workflows."""
