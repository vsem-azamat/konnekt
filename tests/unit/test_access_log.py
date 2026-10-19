"""The container's own health check is not traffic worth a log line."""

from __future__ import annotations

import logging

import pytest
from app.core.logging import QuietHealthChecks


def _access(path: str) -> logging.LogRecord:
    # uvicorn.access's record: (client, method, path, http version, status)
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", path, "1.1", 200),
        None,
    )


@pytest.mark.parametrize("path", ["/api/health", "/api/health?x=1"])
def test_health_checks_are_dropped(path: str) -> None:
    """Every 30 s, for ever: 39,593 of 39,603 lines in the catalog's week were these."""
    assert QuietHealthChecks().filter(_access(path)) is False


@pytest.mark.parametrize("path", ["/api/chats", "/api/healthy-looking", "/api/public/catalog"])
def test_everything_else_is_kept(path: str) -> None:
    assert QuietHealthChecks().filter(_access(path)) is True


def test_the_filter_is_attached_by_logging_setup() -> None:
    import logging

    from app.core.logging import setup_logging

    setup_logging()

    assert any(isinstance(f, QuietHealthChecks) for f in logging.getLogger("uvicorn.access").filters)
