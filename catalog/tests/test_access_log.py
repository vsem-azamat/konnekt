"""The container's own health check is not traffic worth a log line."""

import logging

import pytest

from students_cz.main import QuietHealthChecks


def _access(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", path, "1.1", 200),
        None,
    )


def test_healthz_is_dropped() -> None:
    """39,593 of 39,603 lines in a week were the healthcheck."""
    assert QuietHealthChecks().filter(_access("/healthz")) is False


@pytest.mark.parametrize("path", ["/api/v1/search", "/healthzz"])
def test_everything_else_is_kept(path: str) -> None:
    assert QuietHealthChecks().filter(_access(path)) is True


def test_the_filter_is_attached_when_the_app_is_built() -> None:
    from students_cz.main import create_app

    create_app()

    assert any(isinstance(f, QuietHealthChecks) for f in logging.getLogger("uvicorn.access").filters)
