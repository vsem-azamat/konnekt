"""Every console route refuses a caller without a session.

The guard sits on the console routers in main.py; a router included without
it, or a route added on the app directly, would serve strangers and pass every
other test. This walks the app's own routes instead of a list somebody keeps.
"""

from __future__ import annotations

import re

import pytest
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

# Open on purpose: the public half answers strangers, health answers the
# container's check, and sign-in issues the session.
_OPEN_PREFIXES = ("/api/public", "/api/health")
_OPEN_ROUTES = {("POST", "/api/auth/webapp")}


def _console_routes() -> list[tuple[str, str]]:
    # The schema, because FastAPI resolves included routers lazily and
    # app.routes does not list them. No route here is hidden from it.
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api") or path.startswith(_OPEN_PREFIXES):
            continue
        # Any value will do: the refusal comes before the path is looked at.
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        routes.extend(
            (method.upper(), concrete) for method in sorted(operations) if (method.upper(), path) not in _OPEN_ROUTES
        )
    return routes


def test_the_sweep_sees_the_console() -> None:
    """A sweep over nothing would pass forever; it found none at first."""
    paths = {path for _, path in _console_routes()}

    assert len(paths) >= 10
    assert any(path.startswith("/api/admin") for path in paths)


@pytest.fixture
def with_database(db_session_maker, authenticated_super_admin):
    """The real guard over the test database.

    The webapi tests' autouse fixture lets every request in as a super admin;
    this one takes that away again, since the guard is the thing under test.
    """
    from app.webapi.deps import get_session, require_super_admin

    async def _session():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides.pop(require_super_admin, None)
    app.dependency_overrides[get_session] = _session
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize(("method", "path"), _console_routes())
async def test_a_console_route_refuses_without_a_session(method: str, path: str, with_database) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json={})

    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


@pytest.mark.parametrize("path", ["/api/openapi.json", "/api/docs", "/redoc"])
async def test_production_does_not_publish_a_map_of_the_console(path: str, monkeypatch) -> None:
    from app.core.config import settings
    from app.webapi.main import create_app

    monkeypatch.setattr(settings, "environment", "production")
    production = create_app()
    async with AsyncClient(transport=ASGITransport(app=production), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 404
