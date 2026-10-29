"""A cookie alone does not authorise a write: the page that sent it must be ours.

The console's cookie is `SameSite=Lax`, and Lax is *same-site*: another host
under the same registrable domain still sends it. A body of `text/plain` skips
the CORS preflight, and the API parses a JSON body whatever its content type,
so Lax was the only thing between a sibling subdomain and every console write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.core.config import settings
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

PUBLIC = "https://app.example.test"
ADMIN = "https://admin.example.test"


@pytest.fixture
def client(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session

    async def _session():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    saved = (settings.webapi.public_url, settings.webapi.admin_url)
    settings.webapi.public_url, settings.webapi.admin_url = PUBLIC, ADMIN
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    settings.webapi.public_url, settings.webapi.admin_url = saved
    app.dependency_overrides.pop(get_session, None)


def _cookie() -> dict[str, str]:
    return {"Cookie": f"{settings.webapi.session_cookie_name}=anything"}


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.example.test", "https://sibling.example.test", PUBLIC + ".evil.test"]
)
async def test_a_write_with_a_cookie_from_anywhere_else_is_refused(client, origin) -> None:
    headers = _cookie() | ({"Origin": origin} if origin else {})
    async with client:
        resp = await client.post("/api/auth/logout", headers=headers)

    assert resp.status_code == 403


@pytest.mark.parametrize("origin", [PUBLIC, ADMIN])
async def test_a_write_from_one_of_our_pages_goes_through(client, origin) -> None:
    async with client:
        resp = await client.post("/api/auth/logout", headers=_cookie() | {"Origin": origin})

    assert resp.status_code == 204


async def test_a_write_without_a_cookie_is_not_this_guards_business(client) -> None:
    """Nothing rides along to be abused; the endpoint's own checks apply."""
    async with client:
        resp = await client.post("/api/auth/logout", headers={"Origin": "https://evil.example.test"})

    assert resp.status_code == 204


async def test_a_read_with_a_cookie_and_no_origin_goes_through(client) -> None:
    async with client:
        resp = await client.get("/api/auth/me", headers=_cookie())

    assert resp.status_code != 403


async def test_the_admin_site_is_an_allowed_origin(client) -> None:
    assert settings.webapi.allowed_origins == [PUBLIC, ADMIN]


@pytest.mark.parametrize("origin", ["https://localhost:5173", "http://localhost:5173"])
async def test_with_no_url_configured_the_dev_server_may_write(client, origin) -> None:
    """Vite serves over https (mkcert), or http with VITE_NO_HTTPS=1; its proxy keeps the Origin."""
    settings.webapi.public_url, settings.webapi.admin_url = "", ""
    async with client:
        resp = await client.post("/api/auth/logout", headers=_cookie() | {"Origin": origin})

    assert resp.status_code == 204


async def test_the_example_env_names_the_dev_server_as_it_is_served() -> None:
    """The dev server serves https by default, and the Mini App URL is https or nothing."""
    from pathlib import Path

    example = (Path(__file__).parents[2] / ".env.example").read_text()
    public_url = next(line.split("=", 1)[1] for line in example.splitlines() if line.startswith("WEBAPI_PUBLIC_URL="))

    assert public_url == "https://localhost:5173"
