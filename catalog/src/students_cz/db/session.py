from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from students_cz.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """The one engine, and with it the one connection pool.

    A module-level singleton rather than something on `app.state`, because the
    API is not the only door: the bot's middleware, the notifier's background
    task and the seed scripts all need a session and none of them has a
    FastAPI app to reach through. One pool for all of them is the point — a
    second engine would double the connection count against Postgres without
    anybody deciding to.

    A session is not a connection. `session_scope` makes one per request; the
    connection underneath it is checked out of this pool on the first query
    and handed back when the session closes.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.sqlalchemy_url,
            echo=settings.db_echo,
            # A database error quotes the statement's parameters in its
            # message: names, ids. The message reaches the logs.
            hide_parameters=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        # expire_on_commit=False: without it, touching any attribute after a
        # commit triggers a lazy refresh, which in async code raises
        # MissingGreenlet instead of doing anything useful.
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def unit_of_work(session: AsyncSession) -> AsyncGenerator[AsyncSession]:
    """Commit on the way out, roll back on a raise.

    Separate from `session_scope` so the test fixture can wrap its own session
    in the same rule rather than reimplementing it — a fixture more forgiving
    than production hides exactly the bugs this exists to prevent.
    """
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        await session.commit()


async def session_scope() -> AsyncIterator[AsyncSession]:
    """One transaction per request.

    A unit of work rather than a bare provider. Without it every endpoint has
    to remember to put its commit after the last thing that can fail, and the
    one that did not left an answer in the database that its author was never
    told about.

    Depended on with `scope="function"`: FastAPI runs the teardown of a
    request-scoped dependency after the response has been sent and after its
    background tasks have run, which would mean notifying somebody about a
    write before it committed, and answering a success to a request whose
    commit then failed. The function stack closes earlier — after the handler
    has returned and its response model has been validated, and before the
    response is sent — so a serialisation error rolls back too.
    """
    async with get_sessionmaker()() as session, unit_of_work(session) as scoped:
        yield scoped


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
