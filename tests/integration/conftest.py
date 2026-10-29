"""PostgreSQL test fixtures using testcontainers.

Provides a real PostgreSQL database for integration/e2e tests.
Requires Docker access (user must be in 'docker' group).

Usage in tests:
    @pytest.mark.integration
    async def test_something(pg_session: AsyncSession):
        ...
"""

import pytest
import pytest_asyncio
from app.db.base import Base
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Skip entire module if docker is unavailable
_docker_available = False
try:
    import docker

    client = docker.from_env()
    client.ping()
    _docker_available = True
except Exception:
    pass

pytestmark = pytest.mark.skipif(not _docker_available, reason="Docker not available")


@pytest.fixture(scope="session")
def pg_container():
    """Start a PostgreSQL container for the test session."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:0.8.6-pg18-bookworm", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_url(pg_container) -> str:
    """Get async connection URL from the running container."""
    url = pg_container.get_connection_url()
    return url.replace("psycopg2", "asyncpg")


@pytest_asyncio.fixture()
async def pg_engine(pg_url: str):
    """Create async engine per-test to avoid event loop issues.

    Using TRUNCATE RESTART IDENTITY CASCADE for cleanup (faster than
    iterating Base.metadata.sorted_tables with delete). create_all still
    runs per-test because a session-scoped engine fails with
    'Event loop is closed' once pytest-asyncio closes the function-scoped
    loop (asyncpg connections are tied to the loop that created them)."""
    engine = create_async_engine(pg_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        if table_names:
            await conn.execute(sa_text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture()
async def pg_session(pg_engine: AsyncEngine):
    """Per-test async session."""
    factory = async_sessionmaker(
        bind=pg_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture()
async def pg_session_maker(pg_engine: AsyncEngine):
    """Session maker factory — used where code needs to create its own sessions."""
    return async_sessionmaker(
        bind=pg_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
