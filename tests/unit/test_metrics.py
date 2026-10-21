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


def test_no_label_of_any_series_can_carry_a_person_or_a_chat() -> None:
    """Series are per kind; ids come from the logs. Reads the labels of every metric this app defines."""
    import app.captcha.metrics as captcha_metrics
    import app.presentation.telegram.metrics as bot_metrics
    from prometheus_client.metrics import MetricWrapperBase

    # kind, platform and reason: the Mini App's failures, each a fixed set the
    # route maps anything unknown into (app/webapi/routes/client_errors.py).
    allowed = {
        "method",
        "route",
        "status",
        "level",
        "outcome",
        "update_type",
        "event",
        "queue",
        "kind",
        "platform",
        "reason",
    }
    labels: set[str] = set()
    for module in (metrics, captcha_metrics, bot_metrics):
        for value in vars(module).values():
            if isinstance(value, MetricWrapperBase):
                labels |= set(value._labelnames)  # noqa: SLF001 — the only list of them there is

    assert labels
    assert labels <= allowed, labels - allowed


@pytest.mark.parametrize("short", ["x", "a" * 31, " " + "a" * 30 + " "])
def test_a_short_secret_refuses_to_start(short: str) -> None:
    from app.core.config import ObservabilitySettings

    with pytest.raises(ValueError, match="32 characters"):
        ObservabilitySettings(metrics_secret=short)


def test_a_long_enough_secret_is_kept_and_blank_is_off() -> None:
    from app.core.config import ObservabilitySettings

    assert ObservabilitySettings(metrics_secret=" " + "k" * 32 + "\n").metrics_secret.get_secret_value() == "k" * 32
    assert ObservabilitySettings(metrics_secret="  ").metrics_secret.get_secret_value() == ""


def test_the_scrape_port_cannot_be_moved_by_an_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The compose mapping hard-codes the container side."""
    from app.core.config import ObservabilitySettings

    monkeypatch.setenv("OBSERVABILITY_METRICS_PORT", "9999")

    assert ObservabilitySettings().metrics_port == 8789


def test_failure_counters_exist_before_the_first_failure() -> None:
    """`increase()` counts nothing for a series whose first sample is already 1, so a rare
    failure's first report would never reach an alert. Every series is there from the start.

    A fresh interpreter: in this process earlier tests have already incremented some series.
    """
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        from typing import get_args

        from app.captcha import metrics as _captcha  # noqa: F401
        from app.db.models import JoinCaptcha
        from app.webapi.routes import client_errors
        from prometheus_client import REGISTRY

        def has(name, **labels):
            return REGISTRY.get_sample_value(name, labels) is not None

        statuses = {v for k, v in vars(JoinCaptcha).items() if k.startswith("STATUS_")} - {JoinCaptcha.STATUS_PENDING}
        missing = [("captcha", e) for e in statuses | {"sent", "retry"} if not has("captcha_events_total", event=e)]
        missing += [
            ("client", k, p)
            for k in get_args(client_errors.Kind)
            for p in (*client_errors.PLATFORMS, "other")
            if not has("mini_app_client_errors_total", kind=k, platform=p)
        ]
        missing += [
            ("dropped", r)
            for r in ("invalid", "rate_limited", "overall_limit")
            if not has("mini_app_client_errors_dropped_total", reason=r)
        ]
        print(missing)
        raise SystemExit(1 if missing else 0)
        """
    )
    done = subprocess.run(  # noqa: S603  (our own interpreter, our own script)
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert done.returncode == 0, done.stdout + done.stderr
