"""What Prometheus reads from the catalog API.

Series are per route template and per kind, never per person: the catalog's
people are the audience, whose ids stay out of the telemetry as they stay out
of the logs.

The endpoint is closed by `OBSERVABILITY_METRICS_SECRET`, which is also its
switch: unset, nothing answers. It is read over the public address like the
rest of the site, so the token is the whole lock.
"""

import hmac
import logging

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from students_cz.core.config import get_settings

# Fixed set: a request line may carry any verb, and a series is not free.
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
UNMATCHED = "unmatched"

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests served", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request time, from the first byte in to the last out",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
HTTP_IN_PROGRESS = Gauge("http_requests_in_progress", "HTTP requests being served now")
LOG_RECORDS = Counter("app_log_records_total", "Log records written, by level", ["level"])
# sent, blocked (the person stopped the bot), flood (Telegram asked to wait), failed.
NOTIFICATIONS = Counter(
    "catalog_notifications_total", "Messages the catalog tried to send", ["outcome"]
)


def observe_request(method: str, route: str | None, status: int, seconds: float) -> None:
    method = method if method in _METHODS else "other"
    route = route or UNMATCHED
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(seconds)


class LogCounter(logging.Handler):
    """Counts every record that reaches the `students_cz` logger, by level."""

    def emit(self, record: logging.LogRecord) -> None:
        LOG_RECORDS.labels(level=record.levelname.lower()).inc()


def enabled() -> bool:
    return bool(get_settings().observability_metrics_secret.get_secret_value())


def authorized(authorization: str | None) -> bool:
    """`Authorization: Bearer <secret>`, in constant time; never true while disabled."""
    secret = get_settings().observability_metrics_secret.get_secret_value()
    if not secret or not authorization:
        return False
    scheme, _, presented = authorization.partition(" ")
    return scheme == "Bearer" and hmac.compare_digest(presented.encode(), secret.encode())


def render() -> tuple[bytes, str]:
    """The exposition text and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
