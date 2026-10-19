"""Tests for dependency injection in handlers.

This test suite validates that all handlers receive the correct dependencies
and prevents errors like missing user_service parameters.
"""

import inspect
from typing import get_type_hints
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Message
from app.moderation.user_service import UserService
from app.presentation.telegram.handlers import (
    admin,
    moderation,
    service,
    start,
)
from app.presentation.telegram.middlewares.dependencies import DependenciesMiddleware


@pytest.mark.handlers
class TestDependencyInjection:
    """Test cases for dependency injection in handlers."""

    async def test_dependencies_middleware_provides_all_services(self):
        """Test that DependenciesMiddleware provides all expected dependencies."""
        from unittest.mock import MagicMock

        from sqlalchemy.ext.asyncio import AsyncSession

        # Create mock session maker that returns a mock session via async context manager
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_maker = MagicMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None
        mock_session_maker.return_value = mock_session_context

        mock_bot = AsyncMock()

        middleware = DependenciesMiddleware(mock_session_maker, mock_bot)

        # Exactly these, no more: every entry is built on every update, so one
        # nobody asks for is work done for nothing on each message the bot sees.
        expected_keys = {
            "bot",
            "db",
            "admin_repo",
            "user_repo",
            "chat_repo",
            "message_repo",
            "user_service",
        }

        # Call middleware with a mock handler that captures the data dict
        captured_data = {}

        async def mock_handler(event, data):
            captured_data.update(data)

        mock_event = AsyncMock()
        await middleware(mock_handler, mock_event, {})

        assert set(captured_data) == expected_keys

    def test_user_service_properly_constructed(self):
        """Test that UserService is properly constructed with UserRepository."""
        from app.moderation.user_service import UserService

        # Verify UserService constructor signature
        sig = inspect.signature(UserService.__init__)
        params = list(sig.parameters.keys())

        assert "user_repository" in params, "UserService should accept user_repository parameter"

        # Verify parameter type annotation
        type_hints = get_type_hints(UserService.__init__)
        assert "user_repository" in type_hints, "UserService should have type hint for user_repository"

    def test_blacklist_handlers_expect_user_service(self):
        """Test that blacklist-related handlers expect UserService dependency."""
        from app.presentation.telegram.handlers.moderation import (
            handle_blacklist_pagination,
            show_blacklist,
        )

        # Test show_blacklist handler
        sig = inspect.signature(show_blacklist)
        params = list(sig.parameters.keys())
        type_hints = get_type_hints(show_blacklist)

        assert "user_service" in params, "show_blacklist should accept user_service parameter"
        assert type_hints.get("user_service") == UserService, "user_service should be typed as UserService"

        # Test handle_blacklist_pagination handler
        sig = inspect.signature(handle_blacklist_pagination)
        params = list(sig.parameters.keys())
        type_hints = get_type_hints(handle_blacklist_pagination)

        assert "user_service" in params, "handle_blacklist_pagination should accept user_service parameter"
        assert type_hints.get("user_service") == UserService, "user_service should be typed as UserService"

    def test_all_handler_dependencies_are_available(self):
        """Test that all handler dependencies can be satisfied by middleware."""
        # Define what dependencies the middleware provides
        available_dependencies = {
            "bot",
            "db",
            "admin_repo",
            "user_repo",
            "chat_repo",
            "chat_link_repo",
            "message_repo",
            "user_service",
        }

        # Note: We could define expected types but don't need them for this test
        # expected_types = {...}

        # Get all handler modules
        handler_modules = [admin, moderation, start, service]

        handler_functions = []
        for module in handler_modules:
            for name in dir(module):
                obj = getattr(module, name)
                if (
                    callable(obj)
                    and not name.startswith("_")
                    and hasattr(obj, "__annotations__")
                    and not inspect.isclass(obj)
                    and not name.startswith("build_")  # Exclude utility functions
                    # Handlers defined here, not helpers the module imports.
                    and getattr(obj, "__module__", "").startswith(module.__name__)
                ):
                    # Additional check: only include functions that might be handlers
                    # (they should have message, callback, or similar parameters)
                    sig = inspect.signature(obj)
                    param_names = list(sig.parameters.keys())
                    if any(param in param_names for param in ("message", "callback", "query", "update", "event")):
                        handler_functions.append((f"{module.__name__}.{name}", obj))

        # Check each handler function
        missing_dependencies = []
        for handler_name, handler_func in handler_functions:
            try:
                sig = inspect.signature(handler_func)
                # type_hints = get_type_hints(handler_func)  # Not needed for this test

                for param_name, param in sig.parameters.items():
                    # Skip 'self' and aiogram types that are injected automatically
                    if param_name in ("self", "message", "callback", "query", "callback_data"):
                        continue
                    if param.annotation in (Message, CallbackQuery):
                        continue
                    if hasattr(param.annotation, "__module__") and "aiogram" in str(param.annotation.__module__):
                        continue

                    # Check if this dependency is provided by middleware
                    if param_name not in available_dependencies:
                        missing_dependencies.append(
                            {
                                "handler": handler_name,
                                "missing_param": param_name,
                                "param_type": param.annotation,
                            }
                        )

            except (ValueError, TypeError):
                # Skip handlers that can't be introspected (decorators, etc.)
                pass

        if missing_dependencies:
            error_msg = "Missing dependencies found:\n"
            for dep in missing_dependencies:
                error_msg += f"  {dep['handler']}: missing '{dep['missing_param']}' of type {dep['param_type']}\n"

            pytest.fail(error_msg)
