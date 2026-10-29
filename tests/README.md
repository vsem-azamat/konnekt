# Testing Guide

Practical fixture and factory notes. The contract lives in
[`AGENTS.md`](../AGENTS.md); what the lanes contain is `ls tests/`.

## Quick Start

### Running Tests

```bash
# Install dependencies
uv sync --dev

# Run all tests
uv run -m pytest

# Run specific test categories
uv run -m pytest tests/unit          # Unit tests only
uv run -m pytest tests/integration   # Integration tests only
uv run -m pytest tests/e2e           # End-to-end tests only
uv run -m pytest tests/handlers      # Handler tests only

# Run with coverage
uv run -m pytest --cov=app --cov-report=html

# Fast subset (unit + e2e, stop on first failure)
uv run -m pytest tests/unit tests/e2e -x
```

### Test Markers

```bash
uv run -m pytest -m unit           # Unit tests
uv run -m pytest -m integration    # Integration tests
uv run -m pytest -m e2e            # End-to-end tests
uv run -m pytest -m "not slow"     # Exclude slow tests
```

## Fixtures

Available in all tests (from root `conftest.py`):

- `db_engine` / `engine` - SQLite in-memory async engine
- `session_maker` / `db_session_maker` - Async session maker
- `session` - Database session with savepoint isolation
- `user_repository` - User repository instance
- `chat_repository` - Chat repository instance
- `admin_repository` - Admin repository instance
- `sample_user_data` - Sample user data dictionary
- `sample_chat_data` - Sample chat data dictionary

Available in `tests/telegram_helpers.py` (auto-discovered by pytest):

- `telegram_factory` - `TelegramObjectFactory` instance
- `mock_bot` - `MockBot` instance

Available in `tests/e2e/conftest.py`:

- `fake_tg` - `FakeTelegramServer` instance

## Test Factories

```python
from tests.factories import UserFactory, ChatFactory, AdminFactory

# Create single entities
user = UserFactory.create(username="testuser")
chat = ChatFactory.create_with_welcome("Welcome message")
admin = AdminFactory.create_inactive()

# Create batches
users = UserFactory.create_batch(10)
chats = ChatFactory.create_batch(5, is_forum=True)
```

## Test Infrastructure

### FakeTelegramServer

An aiohttp-based server that simulates the Telegram Bot API. Used in e2e tests to verify that the bot sends correct API requests without hitting real Telegram servers.

### SQLite In-Memory

Unit and e2e tests use SQLite in-memory databases for speed. Integration tests requiring PostgreSQL-specific features (pgvector, etc.) use testcontainers.

### Testcontainers

Integration tests in `tests/integration/conftest.py` use `testcontainers[postgres]` with the `pgvector/pgvector:0.8.6-pg18-bookworm` image, the one CI and production run. Requires Docker access.

## Writing Tests

### Async Testing

All async tests are auto-detected by pytest-asyncio (configured in `pyproject.toml`):

```python
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Error Testing

```python
async def test_user_not_found_raises_exception(user_service):
    with pytest.raises(UserNotFoundException) as exc_info:
        await user_service.get_user_by_id(999999)
    assert exc_info.value.user_id == 999999
```

## Running in CI

Pre-commit hooks run ruff + ty on commit, pytest on push.

```bash
# Quality checks
ruff check app tests && ruff format app tests
ty check app tests

# Full test suite
uv run -m pytest --cov=app
```
