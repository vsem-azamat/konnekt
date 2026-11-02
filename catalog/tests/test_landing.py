"""The one endpoint a browser is allowed to hit.

The landing page's button points at `/api/v1/open`, so the bot's handle lives
in the token the server already has rather than in the frontend bundle and the
build. That makes this the only unauthenticated route in the API, which is
worth pinning down.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
        "uni-cvut&startapp=x",  # anything else rides along into the link
    ],
)
async def test_open_starts_only_where_the_catalog_knows(app_with, start: str) -> None:
    """A start the catalog does not know opens the app itself, never a guess."""
    app = await app_with(StubBot("student_cz_bot"))

    async with await _client(app) as http:
        response = await http.get("/api/v1/open", params={"start": start})

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/student_cz_bot?startapp"
