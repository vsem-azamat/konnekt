"""What the scrape endpoints let in, and what the counters count."""

from __future__ import annotations

import logging

import pytest
from app.core import metrics
from app.core.config import settings
from prometheus_client import REGISTRY


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    from pydantic import SecretStr

    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr("s3cret-value"))
    return "s3cret-value"


def test_without_a_secret_there_is_no_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A feature is on when it is configured: an empty secret must not mean "anything goes"."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr(""))

    assert metrics.enabled() is False
    assert metrics.authorized("Bearer ") is False
    assert metrics.authorized(None) is False


def test_only_the_bearer_secret_is_let_in(secret: str) -> None:
    assert metrics.enabled() is True
    assert metrics.authorized(f"Bearer {secret}") is True
    for header in (None, "", secret, f"Bearer {secret}x", "Bearer wrong", f"Basic {secret}", f"bearer {secret}"):
        assert metrics.authorized(header) is False, header


def test_a_request_is_counted_by_route_and_status() -> None:
    before = sample("http_requests_total", method="GET", route="/api/x/{id}", status="200")

    metrics.observe_request("GET", "/api/x/{id}", 200, 0.02)

    assert sample("http_requests_total", method="GET", route="/api/x/{id}", status="200") == before + 1
    assert sample("http_request_duration_seconds_count", method="GET", route="/api/x/{id}") >= 1


def test_what_no_route_took_shares_one_label_and_odd_methods_another() -> None:
    """Whatever a scanner asks for must not become a series of its own."""
    metrics.observe_request("GET", None, 404, 0.001)
    metrics.observe_request("BREW", None, 404, 0.001)

    assert sample("http_requests_total", method="GET", route="unmatched", status="404") >= 1
    assert sample("http_requests_total", method="other", route="unmatched", status="404") >= 1


def test_log_lines_are_counted_by_level() -> None:
    before = sample("app_log_records_total", level="error")
    counter = metrics.LogCounter()

    counter.handle(logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, None))
    counter.handle(logging.LogRecord("x", logging.WARNING, __file__, 1, "hm", None, None))

    assert sample("app_log_records_total", level="error") == before + 1
    assert sample("app_log_records_total", level="warning") >= 1


def test_setup_logging_counts_the_root_loggers_lines() -> None:
    from app.core.logging import setup_logging

    setup_logging()
    setup_logging()
    root = logging.getLogger()

    assert sum(isinstance(h, metrics.LogCounter) for h in root.handlers) == 1


def test_no_label_carries_a_person_or_a_chat() -> None:
    """Series are per route and per kind, never per id: ids come from the logs."""
    allowed = {"method", "route", "status", "level", "outcome", "update_type", "event", "queue", "handler"}
    assert allowed >= metrics.LABEL_NAMES
