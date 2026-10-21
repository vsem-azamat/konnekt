"""One line per request, findable by the id the caller is also given back."""

from __future__ import annotations

import pytest
import structlog
from app.webapi.main import app
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def probe_routes():
    """Routes that need nothing, so the test is about the log and not a database."""
    router = APIRouter()

    @router.get("/api/_item/{item}")
    async def item(item: str) -> dict[str, str]:
        structlog.get_logger("probe").info("inside")
        return {"item": item}

    @router.get("/api/_boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    app.include_router(router)
    prefixed = APIRouter(prefix="/api/_nest")

    @prefixed.get("/{a}/mid/{b}")
    async def nested(a: str, b: str) -> dict[str, str]:
        return {"a": a, "b": b}

    app.include_router(prefixed)
    yield
    app.router.routes[:] = [
        r
        for r in app.router.routes
        if not getattr(r, "path", "").startswith(("/api/_item", "/api/_boom", "/api/_nest"))
    ]


@pytest.fixture(autouse=True)
def uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """structlog caches a logger on first use, and then `capture_logs` cannot reach it."""
    from app.webapi import request_log

    monkeypatch.setattr(request_log, "logger", structlog.get_logger("webapi.request"))


async def _get(path: str, **headers: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)


def _capture():
    return structlog.testing.capture_logs(processors=[structlog.contextvars.merge_contextvars])


async def test_a_request_is_logged_once_with_its_route_status_and_time() -> None:
    with _capture() as logs:
        response = await _get("/api/_item/7?token=secret")

    [line] = [log for log in logs if log["event"] == "http_request"]
    assert line["method"] == "GET"
    assert "path" not in line  # the path carries the ids of the people it is about
    assert "/api/_item/7" not in str(line)
    assert line["route"] == "/api/_item/{item}"
    assert line["status"] == response.status_code
    assert line["duration_ms"] >= 0
    assert line["request_id"] == response.headers["x-request-id"]
    assert "secret" not in str(logs)


async def test_the_callers_request_id_is_kept_when_it_is_well_formed() -> None:
    with _capture() as logs:
        response = await _get("/api/_item/7", **{"X-Request-Id": "abc-123_DEF.456"})

    assert response.headers["x-request-id"] == "abc-123_DEF.456"
    assert {log["request_id"] for log in logs if log["event"] == "http_request"} == {"abc-123_DEF.456"}


@pytest.mark.parametrize("sent", ["short", "x" * 100, "has space in it", "semi;colon;12345"])
async def test_a_malformed_request_id_is_replaced(sent: str) -> None:
    response = await _get("/api/_item/7", **{"X-Request-Id": sent})

    assert response.headers["x-request-id"] != sent
    assert len(response.headers["x-request-id"]) == 32


async def test_lines_written_while_handling_carry_the_request_id() -> None:
    with _capture() as logs:
        response = await _get("/api/_item/7")
        structlog.get_logger("probe").info("outside")

    inside = next(log for log in logs if log["event"] == "inside")
    outside = next(log for log in logs if log["event"] == "outside")
    assert inside["request_id"] == response.headers["x-request-id"]
    assert "request_id" not in outside


async def test_the_health_check_leaves_no_line() -> None:
    with _capture() as logs:
        await _get("/api/health")

    assert [log for log in logs if log["event"] == "http_request"] == []


async def test_a_failing_route_is_logged_with_its_traceback_and_a_500() -> None:
    with _capture() as logs:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            response = await c.get("/api/_boom")

    assert response.status_code == 500
    [line] = [log for log in logs if log["event"] == "http_request"]
    assert line["status"] == 500
    assert line["log_level"] == "error"
    assert line["exc_info"]
    assert line["route"] == "/api/_boom"
    # Answered by the server-error middleware, which RequestLog sits outside of.
    assert response.headers["x-request-id"] == line["request_id"]


async def test_the_route_is_the_template_with_the_prefixes_of_its_routers() -> None:
    with _capture() as logs:
        await _get("/api/_nest/7/mid/9")
        await _get("/wp-login.php")

    found, scanner = [log for log in logs if log["event"] == "http_request"]
    assert found["route"] == "/api/_nest/{a}/mid/{b}"
    assert scanner["route"] is None


async def test_the_server_error_is_reported_once_and_not_handed_on_to_the_server() -> None:
    """Raised again, uvicorn would log the same failure a second time: a second alert."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/api/_boom")  # raise_app_exceptions is on: it would raise here

    assert response.status_code == 500


async def test_the_route_does_not_mistake_a_parameter_for_a_literal_of_the_same_name() -> None:
    with _capture() as logs:
        await _get("/api/_nest/api/mid/api")

    [line] = [log for log in logs if log["event"] == "http_request"]
    assert line["route"] == "/api/_nest/{a}/mid/{b}"


@pytest.mark.parametrize("status", [502, 503])
async def test_an_answer_the_api_gives_on_purpose_is_a_warning_not_an_alert(status: int) -> None:
    from fastapi import HTTPException

    router = APIRouter()

    @router.get(f"/api/_{status}")
    async def refuse() -> None:
        raise HTTPException(status_code=status)

    app.include_router(router)
    try:
        with _capture() as logs:
            await _get(f"/api/_{status}")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != f"/api/_{status}"]

    [line] = [log for log in logs if log["event"] == "http_request"]
    assert line["log_level"] == "warning"
