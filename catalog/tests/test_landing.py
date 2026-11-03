"""The one endpoint a browser is allowed to hit.

The landing page's button points at `/api/v1/open`, so the bot's handle lives
in the token the server already has rather than in the frontend bundle and the
build. It answers without init data, which is worth pinning down.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import Institution

from .conftest import BrokenBot, StubBot, app_for

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_with(session: AsyncSession):
    """An app with a bot of the caller's choosing on its state."""

    async def build(bot) -> FastAPI:
        return app_for(session, bot=bot)

    return build


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_open_redirects_to_the_bot(app_with) -> None:
    bot = StubBot("student_cz_bot")
    app = await app_with(bot)

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot"


async def test_open_can_open_the_mini_app_itself(app_with) -> None:
    """«Открыть Konnekt» on the site opens the app, not the chat with the bot."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"app": "1"})

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp"


async def test_open_needs_no_init_data(app_with) -> None:
    """The whole point: this is reached by someone not in Telegram yet."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 302
    assert "Authorization" not in response.request.headers


async def test_the_landing_asks_telegram_once(app_with) -> None:
    """Every landing visit would otherwise be a round trip to Telegram."""
    bot = StubBot("student_cz_bot")
    app = await app_with(bot)

    async with await _client(app) as http:
        await http.get("/api/v1/open")
        await http.get("/api/v1/open")

    assert bot.calls == 1


async def test_without_a_bot_it_says_so(client: AsyncClient) -> None:
    """The shared client has no bot on its state — the API-only configuration."""
    response = await client.get("/api/v1/open")

    assert response.status_code == 503


async def test_a_failing_telegram_is_not_a_crash(app_with) -> None:
    app = await app_with(BrokenBot())

    async with await _client(app) as http:
        response = await http.get("/api/v1/open")

    assert response.status_code == 503


async def test_open_can_start_on_a_universitys_chats(app_with) -> None:
    """«Открыть в Konnekt» on a university's page opens the app on its chats."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"start": "uni-cvut"})

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp=uni-cvut"


@pytest.mark.parametrize(
    "start",
    [
        "uni-nowhere",  # no such university
        "uni-cvut_fit",  # a faculty: the app's section screen is a university's
        "home",  # a screen the site has no business naming
        "uni-CVUT",  # not the shape of a code, so not looked up
        "uni-\x00",  # which the database would refuse with a 500
        "uni-" + "x" * 5000,
    ],
)
async def test_open_starts_only_where_the_catalog_knows(app_with, start: str) -> None:
    """A start the catalog does not know opens the app itself, never a guess."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"start": start})

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp"


async def test_open_does_not_start_on_a_retired_university(app_with, session) -> None:
    await session.execute(
        update(Institution).where(Institution.code == "cvut").values(is_active=False)
    )
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"start": "uni-cvut"})

    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp"


async def test_open_carries_where_on_the_site_it_was_pressed(app_with) -> None:
    """The site's buttons say which they are, and the app records it as the source."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get(
            "/api/v1/open",
            params={"app": "1", "from": "site_article_nostrifikaciya-attestata"},
        )

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "https://t.me/student_cz_bot?startapp=site_article_nostrifikaciya-attestata"
    )


async def test_a_screen_to_open_comes_before_where_it_was_pressed(app_with) -> None:
    """A university's chats are the start; it is a source of its own."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get(
            "/api/v1/open", params={"start": "uni-cvut", "from": "site_university"}
        )

    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp=uni-cvut"


@pytest.mark.parametrize(
    "source",
    [
        "header",  # not one of the site's own
        "site_",  # nothing after the prefix
        "site_Header",  # not the shape the site writes
        "site_a b",  # a start parameter may not hold it
        "site_" + "x" * 60,  # longer than Telegram takes (64)
    ],
)
async def test_open_passes_on_only_the_sites_own_sources(app_with, source: str) -> None:
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"app": "1", "from": source})

    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp"
