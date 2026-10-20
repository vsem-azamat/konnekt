"""The catalog's console screens, asked for by the console opened in a browser.

There it has no initData, so webapi asks the catalog itself, for the super
admin its session names, with the token the two containers share. See
catalog/docs/architecture.md, «The operator reads the catalog and runs the
partner cards».
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
from app.core.config import settings
from app.webapi.main import app
from app.webapi.origin_guard import DEV_ORIGIN
from app.webapi.routes import catalog
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.asyncio

TOKEN = "shared-between-the-two-containers"  # noqa: S105
CATALOG = "http://catalog.test"


class Catalog:
    """What the catalog was asked, and what it answers."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Callable[[httpx.Request], httpx.Response] = lambda _: httpx.Response(200, json={"ok": True})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Iterator[Catalog]:
    fake = Catalog()
    monkeypatch.setattr(settings.webapi, "catalog_url", CATALOG)
    monkeypatch.setattr(settings.webapi, "catalog_service_token", SecretStr(TOKEN))

    async def _http() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(fake))

    app.dependency_overrides[catalog.get_catalog_http] = _http
    yield fake
    app.dependency_overrides.pop(catalog.get_catalog_http, None)


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": DEV_ORIGIN},
        cookies={settings.webapi.session_cookie_name: "the-console-session"},
    )


ROUTES = [
    ("GET", "/api/catalog/admin/catalog", "/api/v1/admin/catalog"),
    ("GET", "/api/catalog/admin/profiles/7", "/api/v1/admin/profiles/7"),
    ("POST", "/api/catalog/admin/profiles/7/review", "/api/v1/admin/profiles/7/review"),
    ("POST", "/api/catalog/admin/profiles/7/hide", "/api/v1/admin/profiles/7/hide"),
    ("POST", "/api/catalog/admin/profiles/7/restore", "/api/v1/admin/profiles/7/restore"),
    ("GET", "/api/catalog/admin/partners", "/api/v1/admin/partners"),
    ("POST", "/api/catalog/admin/placements", "/api/v1/admin/placements"),
    ("PATCH", "/api/catalog/admin/placements/3", "/api/v1/admin/placements/3"),
    ("GET", "/api/catalog/taxonomy/institutions", "/api/v1/taxonomy/institutions"),
]


@pytest.mark.parametrize(("method", "ours", "theirs"), ROUTES)
async def test_each_screen_is_asked_of_the_catalog_for_the_signed_in_admin(
    upstream: Catalog, method: str, ours: str, theirs: str
) -> None:
    async with _client() as http:
        response = await http.request(method, ours, json={"is_active": False})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    (sent,) = upstream.requests
    assert sent.method == method
    assert str(sent.url) == CATALOG + theirs
    assert sent.headers["X-Catalog-Service"] == TOKEN
    assert sent.headers["X-Catalog-Operator"] == str(settings.admin.super_admins[0])


async def test_only_what_the_catalog_needs_goes_there(upstream: Catalog) -> None:
    """Not the console's cookie, not whatever the browser sent along."""
    async with _client() as http:
        await http.get(
            "/api/catalog/admin/catalog",
            headers={"Authorization": "tma user=...", "X-Catalog-Operator": "1", "X-Forwarded-For": "6.6.6.6"},
        )

    (sent,) = upstream.requests
    assert "cookie" not in sent.headers
    assert "authorization" not in sent.headers
    assert "x-forwarded-for" not in sent.headers
    assert sent.headers["X-Catalog-Operator"] == str(settings.admin.super_admins[0])


async def test_a_card_and_a_switch_carry_their_body(upstream: Catalog) -> None:
    card = {"partner": "Kavárna", "url": "https://example.cz", "title": "Káva"}
    async with _client() as http:
        await http.post("/api/catalog/admin/placements", json=card)
        await http.patch("/api/catalog/admin/placements/3", json={"is_active": False})

    created, switched = upstream.requests
    assert json.loads(created.content) == card
    assert json.loads(switched.content) == {"is_active": False}


async def test_the_console_names_its_language(upstream: Catalog) -> None:
    async with _client() as http:
        named = await http.get("/api/catalog/taxonomy/institutions", params={"lang": "cs"})
        unnamed = await http.get("/api/catalog/taxonomy/institutions")
        unknown = await http.get("/api/catalog/taxonomy/institutions", params={"lang": "xx"})

    assert named.status_code == unnamed.status_code == 200
    assert unknown.status_code == 422
    first, second = upstream.requests
    assert first.headers["X-Catalog-Lang"] == "cs"
    assert "x-catalog-lang" not in second.headers
    # The language is a header there, not part of the address.
    assert first.url.query == b""


@pytest.mark.parametrize("status", [403, 404, 409, 422])
async def test_the_catalogs_answer_comes_back_as_it_was(upstream: Catalog, status: int) -> None:
    upstream.answer = lambda _: httpx.Response(status, json={"detail": "the catalog's own words"})
    async with _client() as http:
        response = await http.post("/api/catalog/admin/profiles/7/hide")

    assert response.status_code == status
    assert response.json() == {"detail": "the catalog's own words"}


async def test_the_catalog_refusing_the_token_is_not_the_admins_session(upstream: Catalog) -> None:
    """A 401 from there means the containers disagree, not that the browser
    must sign in again, which is what a 401 tells the console."""
    upstream.answer = lambda _: httpx.Response(401, json={"detail": "service call rejected"})
    async with _client() as http:
        response = await http.get("/api/catalog/admin/catalog")

    assert response.status_code == 502


async def test_an_unreachable_catalog_is_a_bad_gateway(upstream: Catalog) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    upstream.answer = refuse
    async with _client() as http:
        response = await http.get("/api/catalog/admin/catalog")

    assert response.status_code == 502


async def test_without_a_token_nothing_is_asked(upstream: Catalog, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.webapi, "catalog_service_token", SecretStr(""))
    async with _client() as http:
        response = await http.get("/api/catalog/admin/catalog")

    assert response.status_code == 503
    assert upstream.requests == []


@pytest.mark.parametrize("path", ["/api/catalog/admin/profiles/0", "/api/catalog/admin/placements/-1/x"])
async def test_an_address_the_catalog_has_no_screen_for_is_not_asked(upstream: Catalog, path: str) -> None:
    async with _client() as http:
        response = await http.get(path)

    assert response.status_code in (404, 405, 422)
    assert upstream.requests == []


def test_the_token_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import WebApiSettings

    monkeypatch.setenv("WEBAPI_CATALOG_SERVICE_TOKEN", TOKEN)
    configured = WebApiSettings(_env_file=None)
    assert configured.catalog_service_token.get_secret_value() == TOKEN
    assert TOKEN not in repr(configured)
    assert configured.catalog_url == "http://catalog-api:8000"
