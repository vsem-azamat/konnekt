import os
from collections.abc import AsyncGenerator
from typing import Any

# Setup test environment variables BEFORE any application imports
# This ensures configuration is available when modules are loaded
os.environ.update(
    {
        "DB_USER": "test",
        "DB_PASSWORD": "test",
        "DB_NAME": "test",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "MODERATOR_BOT_TOKEN": "123456:ABC-DEF1234567890",
        "ADMIN_SUPER_ADMINS": "[123456789, 987654321]",  # JSON format for list
        "ADMIN_REPORT_CHAT_ID": "123456789",
        "LOG_LEVEL": "ERROR",  # Reduce logging noise in tests
        "APP_ENVIRONMENT": "test",
    }
)

import pytest
import pytest_asyncio
from app.db.base import Base
from app.db.repositories.admin import AdminRepository
from app.db.repositories.chat import ChatRepository
from app.db.repositories.user import UserRepository
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


# Alias for backward compat — some tests use `engine`
engine = db_engine


@pytest_asyncio.fixture(scope="function")
async def session_maker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Async session maker bound to the in-memory engine."""
    return async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


# Alias — escalation tests use `db_session_maker`
db_session_maker = session_maker


@pytest_asyncio.fixture(scope="function")
async def session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for tests with proper isolation."""
    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    async with factory() as sess:
        nested_transaction = await sess.begin_nested()
        try:
            yield sess
        finally:
            if nested_transaction.is_active:
                await nested_transaction.rollback()


@pytest_asyncio.fixture()
async def user_repository(session: AsyncSession) -> UserRepository:
    """Create user repository for tests."""
    return UserRepository(session)


@pytest_asyncio.fixture()
async def chat_repository(session: AsyncSession) -> ChatRepository:
    """Create chat repository for tests."""
    return ChatRepository(session)


@pytest_asyncio.fixture()
async def admin_repository(session: AsyncSession) -> AdminRepository:
    """Create admin repository for tests."""
    return AdminRepository(session)


@pytest.fixture
def audit_db():
    """A stand-in session that keeps the moderation events written through it.

    Handler tests drive the handlers directly, with no database behind them, but
    every moderation command now writes one row. This lets them assert on the
    row itself instead of mocking a session and checking that something happened.
    """
    from tests.telegram_helpers import RecordingSession

    return RecordingSession()


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample user data for tests."""
    return {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User",
    }


@pytest.fixture
def sample_chat_data() -> dict[str, Any]:
    """Sample chat data for tests."""
    return {
        "id": -1001234567890,
        "title": "Test Chat",
        "is_forum": False,
    }


@pytest.fixture(autouse=True)
def _fresh_throttles() -> None:
    """Refusal and report throttles are per process; a test must not inherit another's window."""
    from app.presentation.telegram.handlers.groups import forget_reports
    from app.presentation.telegram.middlewares.admin import forget_refusals

    forget_reports()
    forget_refusals()


@pytest.fixture(autouse=True)
def _fresh_welcomes() -> None:
    """A greeting still up in one test's chat must not be edited by the next test's joiner."""
    from app.chats.welcome import forget

    forget()
