"""Logs a shipper can read: one JSON line a record, and a request id to follow."""

import json
import logging
import sys
from types import TracebackType

import pytest
from httpx import AsyncClient

from students_cz.core.logs import JsonFormatter, bound
from students_cz.main import configure_logging

from .conftest import auth_header

ExcInfo = (
    tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
)


def _record(
    msg: str,
    *args: object,
    exc_info: ExcInfo | None = None,
    fields: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        "students_cz.x", logging.WARNING, __file__, 1, msg, args, exc_info
    )
    if fields:
        record.fields = fields
    return record


def test_a_record_is_one_json_line_with_its_level_and_logger() -> None:
    line = JsonFormatter().format(_record("init_data_rejected: %s", "expired"))

    parsed = json.loads(line)
    assert "\n" not in line
    assert parsed["event"] == "init_data_rejected: expired"
    assert parsed["logger"] == "students_cz.x"
    assert parsed["level"] == "warning"
    assert parsed["severity"] == "WARNING"
    assert parsed["timestamp"]


def test_the_traceback_stays_in_the_same_line() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record("failed", exc_info=sys.exc_info())

    line = JsonFormatter().format(record)

    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["exception"]


def test_fields_and_bound_context_are_merged() -> None:
    with bound(request_id="abc12345"):
        parsed = json.loads(
            JsonFormatter().format(_record("http_request", fields={"status": 200}))
        )

    assert parsed["status"] == 200
    assert parsed["request_id"] == "abc12345"
    assert "request_id" not in json.loads(JsonFormatter().format(_record("later")))


def test_configuring_puts_the_formatter_where_uvicorn_writes() -> None:
    uvicorn_handler = logging.StreamHandler()
    logging.getLogger("uvicorn.error").addHandler(uvicorn_handler)
    try:
        configure_logging("INFO")
        configure_logging("INFO")

        ours = [
            h
            for h in logging.getLogger("students_cz").handlers
            if isinstance(h.formatter, JsonFormatter)
        ]
        assert len(ours) == 1
        assert isinstance(uvicorn_handler.formatter, JsonFormatter)
    finally:
        logging.getLogger("uvicorn.error").removeHandler(uvicorn_handler)


def test_text_is_still_there_for_a_terminal() -> None:
    configure_logging("INFO", log_format="text")
    try:
        formatters = [h.formatter for h in logging.getLogger("students_cz").handlers]
        assert not any(isinstance(f, JsonFormatter) for f in formatters)
    finally:
        configure_logging("INFO", log_format="json")


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(JsonFormatter().format(record)))


@pytest.fixture
def collected():
    handler = _Collect()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = logging.getLogger("students_cz").level
    logging.getLogger("students_cz").setLevel(logging.INFO)
    yield handler.lines
    logging.getLogger("students_cz").setLevel(previous)
    root.removeHandler(handler)


async def test_a_request_is_one_line_with_route_status_time_and_id(
    client: AsyncClient, collected: list[dict]
) -> None:
    response = await client.get(
        "/api/v1/taxonomy/languages?secret=1", headers={"X-Request-Id": "req-12345678"}
    )

    [line] = [entry for entry in collected if entry["event"] == "http_request"]
    assert line["method"] == "GET"
    assert line["path"] == "/api/v1/taxonomy/languages"  # never the query string
    assert line["route"] == "/api/v1/taxonomy/languages"
    assert line["status"] == response.status_code
    assert line["duration_ms"] >= 0
    assert line["request_id"] == "req-12345678" == response.headers["x-request-id"]
    assert "secret" not in str(collected)


async def test_the_route_is_the_template_with_its_prefixes(
    client: AsyncClient, collected: list[dict]
) -> None:
    await client.get("/api/v1/requests/999999/responses", headers=auth_header())

    [line] = [entry for entry in collected if entry["event"] == "http_request"]
    assert line["path"] == "/api/v1/requests/999999/responses"
    assert line["route"] == "/api/v1/requests/{request_id}/responses"


async def test_a_path_no_route_took_has_no_route(
    client: AsyncClient, collected: list[dict]
) -> None:
    await client.get("/wp-login.php")

    [line] = [entry for entry in collected if entry["event"] == "http_request"]
    assert line["status"] == 404
    assert line["route"] is None


async def test_a_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-Id": "bad id"})

    assert response.headers["x-request-id"] != "bad id"
    assert len(response.headers["x-request-id"]) == 32


async def test_the_health_check_leaves_no_line(
    client: AsyncClient, collected: list[dict]
) -> None:
    await client.get("/healthz")

    assert [entry for entry in collected if entry["event"] == "http_request"] == []


async def test_a_refused_request_is_a_warning(
    client: AsyncClient, collected: list[dict]
) -> None:
    response = await client.get(
        "/api/v1/taxonomy/languages", headers={"Authorization": "tma garbage"}
    )

    [line] = [entry for entry in collected if entry["event"] == "http_request"]
    assert response.status_code == 401
    assert line["level"] == "warning"


async def test_a_failing_route_is_an_error_line_with_its_traceback(
    session, collected: list[dict]
) -> None:
    from httpx import ASGITransport

    from .conftest import app_for

    app = app_for(session)

    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/_boom")

    [line] = [entry for entry in collected if entry["event"] == "http_request"]
    assert response.status_code == 500
    assert line["level"] == "error"
    assert line["status"] == 500
    assert "RuntimeError: boom" in line["exception"]
