"""The scrape endpoint of the web API is closed by a token, and absent without one."""

from __future__ import annotations

import pytest
import structlog
from app.core.config import settings
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from pydantic import SecretStr

pytestmark = pytest.mark.asyncio


async def _get(path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr("s3cret-value"))
    return "s3cret-value"


async def test_without_a_secret_the_endpoint_does_not_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr(""))

    assert (await _get("/api/internal/metrics")).status_code == 404
    assert (await _get("/api/internal/metrics", "anything")).status_code == 404


async def test_a_wrong_or_missing_token_is_refused(secret: str) -> None:
    assert (await _get("/api/internal/metrics")).status_code == 401
    assert (await _get("/api/internal/metrics", "nope")).status_code == 401


async def test_the_right_token_gets_prometheus_text(secret: str) -> None:
    response = await _get("/api/internal/metrics", secret)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in response.text
    assert "process_resident_memory_bytes" in response.text


async def test_the_endpoint_is_not_in_the_published_schema(secret: str) -> None:
    assert "/api/internal/metrics" not in app.openapi()["paths"]


async def test_a_scrape_is_neither_logged_nor_counted(secret: str) -> None:
    from app.webapi import request_log

    before = REGISTRY.get_sample_value(
        "http_requests_total", {"method": "GET", "route": "/api/internal/metrics", "status": "200"}
    )
    with structlog.testing.capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        # a fresh proxy: structlog caches the module's logger on first use
        request_log.logger = structlog.get_logger("webapi.request")
        await _get("/api/internal/metrics", secret)

    assert [log for log in logs if log["event"] == "http_request"] == []
    after = REGISTRY.get_sample_value(
        "http_requests_total", {"method": "GET", "route": "/api/internal/metrics", "status": "200"}
    )
    assert after == before


async def test_requests_are_counted_by_their_route_template() -> None:
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/_m")

    @router.get("/{thing}")
    async def thing(thing: str) -> dict[str, str]:
        return {"thing": thing}

    app.include_router(router)
    labels = {"method": "GET", "route": "/api/_m/{thing}", "status": "200"}
    before = REGISTRY.get_sample_value("http_requests_total", labels) or 0
    try:
        await _get("/api/_m/one")
        await _get("/api/_m/two")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/_m/{thing}"]

    assert REGISTRY.get_sample_value("http_requests_total", labels) == before + 2
