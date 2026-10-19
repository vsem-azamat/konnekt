"""Tests run against a real Postgres.

The interesting logic is SQL — trigram matching, word-boundary synonyms,
exclusion constraints — and none of it survives being mocked. Each test runs
inside a transaction that is rolled back, so the seeded reference data stays
untouched and tests do not see each other's writes.
"""

import os

# Set before anything imports Settings: tests exercise the API without a bot,
# and minting a validly signed initData per request would only re-test
# aiogram's HMAC. Signature handling has its own tests.
os.environ["ALLOW_UNSIGNED_INIT_DATA"] = "true"
os.environ["BOT_TOKEN"] = ""
# Pinned for the same reason, one step further on: `get_settings` walks up to
# the repository's own `.env`, so without this a notification carries a
# web_app button on a machine that has PUBLIC_BASE_URL set and no button in CI.
# A suite that exercises different code on different machines is not a suite.
os.environ["PUBLIC_BASE_URL"] = "https://tests.example"

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from students_cz.core.config import Settings, get_settings
from students_cz.db.models import (
    HelperProfile,
    Offer,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import PublishStatus, UiLang


@pytest.fixture(autouse=True)
def no_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite answers the same on a machine that has the model and one that
    does not.

    Without this the disk decides: `EMBEDDING_MODEL_DIR` pointing at a real
    model turned the semantic fallback on for every test, and two of them —
    written to pin that a bare «přijímačky» names no subject — failed only
    there. Tests that want an embedder set one explicitly.
    """
    from pathlib import Path

    from students_cz.services import embedding

    monkeypatch.setattr(embedding, "MODEL_DIR", Path("/nonexistent"))
    monkeypatch.setattr(embedding, "_embedder", None)
    monkeypatch.setattr(embedding, "_looked", False)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest_asyncio.fixture
async def engine(settings: Settings):
    # Per-test rather than per-session: an async engine binds to the event loop
    # that created it, and pytest-asyncio gives each test its own.
    engine = create_async_engine(settings.sqlalchemy_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session bound to a transaction that is always rolled back.

    Nested inside an outer transaction, so even code that calls commit() only
    ends the inner one and the whole test still disappears at the end.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        maker = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with maker() as session:
            yield session
        await transaction.rollback()


def app_for(session: AsyncSession, *, bot: object | None = None):
    """The application, wired to this test's session.

    One place, because a test that builds its own app also builds its own idea
    of what a request commits — and the point of the override is that it
    commits and rolls back exactly where `session_scope` does. A fixture that
    is more forgiving than production hides the bugs that rule exists to
    prevent.

    `bot` goes on `app.state` the way the lifespan puts it there, for the tests
    that need the app to have one. Absent by default: the lifespan does not run
    under `ASGITransport`, so "no bot" is what a test sees unless it says
    otherwise, and that is also how the API runs locally.
    """
    from students_cz.db.session import session_scope, unit_of_work
    from students_cz.main import create_app

    # The same rule the real scope applies, not a copy of it. The whole test
    # still disappears: this session is joined to an outer transaction as a
    # savepoint, so its commits end only the inner one.
    async def scope():
        async with unit_of_work(session):
            yield session

    app = create_app()
    app.dependency_overrides[session_scope] = scope
    if bot is not None:
        app.state.bot = bot
    return app


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose requests share the test's rolled-back session."""
    transport = ASGITransport(app=app_for(session))
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def init_data_for(tg_id: int, first_name: str = "Test", **extra) -> str:
    """An unsigned initData payload, accepted only in development mode.

    Signature verification is aiogram's and is tested separately; what these
    tests need is a caller identity, not a re-test of HMAC.
    """
    import json
    from urllib.parse import urlencode

    user = {"id": tg_id, "first_name": first_name, **extra}
    return urlencode({"user": json.dumps(user), "auth_date": "1700000000"})


def auth_header(tg_id: int = 90001, **extra) -> dict[str, str]:
    return {"Authorization": f"tma {init_data_for(tg_id, **extra)}"}


@pytest_asyncio.fixture
async def helper_factory(session: AsyncSession):
    """Create a published helper with one offer, ready to be found."""

    async def make(
        *,
        tg_id: int,
        first_name: str = "Marek",
        last_name: str | None = "N",
        subject_slug: str = "matematicka-analyza",
        service_code: str = "tutoring",
        institution_id: int | None = None,
        price: float | None = 600,
        langs: tuple[str, ...] = ("ru", "cs"),
        deals: int = 0,
    ) -> User:
        from sqlalchemy import select

        user = User(
            tg_id=tg_id,
            first_name=first_name,
            last_name=last_name,
            ui_lang=UiLang.RU,
            spoken_langs=list(langs),
        )
        session.add(user)
        await session.flush()

        helper = HelperProfile(
            user_id=user.id,
            status=PublishStatus.PUBLISHED,
            headline=f"{first_name} teaches things",
            deals_count=deals,
        )
        session.add(helper)

        subject = await session.scalar(
            select(Subject).where(Subject.slug == subject_slug)
        )
        service = await session.scalar(
            select(ServiceType).where(ServiceType.code == service_code)
        )
        assert subject is not None, f"seed missing subject {subject_slug}"
        assert service is not None, f"seed missing service type {service_code}"

        session.add(
            Offer(
                helper_id=user.id,
                service_type_id=service.id,
                subject_id=subject.id,
                institution_id=institution_id,
                price_amount=price,
                langs=list(langs),
            )
        )
        await session.flush()
        return user

    return make


class StubBot:
    """Enough of aiogram's `Bot` to answer "what is your username?"."""

    def __init__(self, username: str | None = "student_cz_bot") -> None:
        self.username = username
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        return SimpleNamespace(username=self.username)


class BrokenBot:
    """A Telegram that is having a moment."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        raise RuntimeError("Telegram is having a moment")


@pytest.fixture(autouse=True)
def _fresh_search_pace() -> None:
    """The search limits are per process; a test must not inherit another's window."""
    from students_cz.api.v1 import search

    search.forget_pace()
