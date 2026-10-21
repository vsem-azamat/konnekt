"""What /healthz is allowed to claim.

The signal the deploy and the shared edge watch. It reports the process and
its database, and nothing about Telegram: this process holds no webhook, the
token is the moderator bot's. See docs/architecture.md.
"""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(session: AsyncSession) -> FastAPI:
    from students_cz.db.session import session_scope, unit_of_work
    from students_cz.main import create_app

    async def scope():
        async with unit_of_work(session):
            yield session

    app = create_app()
    app.dependency_overrides[session_scope] = scope
    return app


async def test_healthz_reports_the_process_and_the_database_only(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "database", "uptime_seconds"}
    assert body["status"] == "ok" and body["database"] == "ok"


async def test_the_application_logger_actually_writes_somewhere() -> None:
    """The half of the incident that made it undiagnosable.

    Uvicorn configures its own loggers and nothing else, so without this the
    `students_cz` logger falls back to Python's last-resort handler, which emits
    WARNING and above. Every `log.info` went nowhere — including the line that
    says semantic search is off.
    """
    import logging

    from students_cz.main import configure_logging

    configure_logging("INFO")
    logger = logging.getLogger("students_cz")

    assert logger.level == logging.INFO
    # On the root, so a library's warnings leave in the same shape as ours.
    assert any(
        isinstance(h, logging.StreamHandler) and getattr(h, "_students_cz_handler", False)
        for h in logging.getLogger().handlers
    )

    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    root = logging.getLogger()
    capture = Capture()
    root.addHandler(capture)
    try:
        logger.info("sent to %s", "tests")
    finally:
        root.removeHandler(capture)

    assert "sent to tests" in seen


async def test_configuring_logging_twice_does_not_double_the_handlers() -> None:
    """`create_app()` runs once per process and once per test."""
    import logging

    from students_cz.main import configure_logging

    def ours() -> int:
        return sum(
            getattr(h, "_students_cz_handler", False)
            for h in logging.getLogger().handlers
        )

    configure_logging("INFO")
    before = ours()
    configure_logging("INFO")
    assert before == 1
    assert ours() == before
