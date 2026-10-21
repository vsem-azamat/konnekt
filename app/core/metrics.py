"""What Prometheus reads from this process.

Series are per route, per kind of update, per level: never per chat or person.
Those ids are in the logs, where a search finds them; as labels they would
make a series for everyone who ever wrote, and the audience's ids stay out of
the telemetry as they stay out of the logs (docs/invariants.md).

The endpoint is closed by `OBSERVABILITY_METRICS_SECRET`, which is also its
switch: unset, there is nothing to scrape and nothing answers. A scrape is
read over the public address like the rest of the site, so the token is the
whole lock.
"""

from __future__ import annotations

import hmac
import logging

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.core.config import settings

# Fixed set: a request line may carry any verb, and a series is not free.
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
UNMATCHED = "unmatched"

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests served", ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request time, from the first byte in to the last out",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
HTTP_IN_PROGRESS = Gauge("http_requests_in_progress", "HTTP requests being served now")
LOG_RECORDS = Counter("app_log_records_total", "Log records written, by level", ["level"])
AVATAR_SYNCS = Counter("chat_avatar_syncs_total", "Chat photo syncs, by what became of the photo", ["outcome"])
ALERTS = Counter("alerts_total", "Error alerts sent to the report chat", ["outcome"])
# What the Mini App reported failing (app/webapi/routes/client_errors.py), and
# what the limits there turned away rather than wrote.
CLIENT_ERRORS = Counter("mini_app_client_errors_total", "Failures the Mini App reported", ["kind", "platform"])
CLIENT_ERRORS_DROPPED = Counter(
    "mini_app_client_errors_dropped_total", "Mini App failure reports past a limit, not written", ["reason"]
)


def observe_request(method: str, route: str | None, status: int, seconds: float) -> None:
    method = method if method in _METHODS else "other"
    route = route or UNMATCHED
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(seconds)


class LogCounter(logging.Handler):
    """Counts every record that reaches the root logger, by level."""

    def emit(self, record: logging.LogRecord) -> None:
        LOG_RECORDS.labels(level=record.levelname.lower()).inc()


def enabled() -> bool:
    return bool(settings.observability.metrics_secret.get_secret_value())


def authorized(authorization: str | None) -> bool:
    """`Authorization: Bearer <secret>`, compared in constant time; never true while disabled."""
    secret = settings.observability.metrics_secret.get_secret_value()
    if not secret or not authorization:
        return False
    scheme, _, presented = authorization.partition(" ")
    return scheme == "Bearer" and hmac.compare_digest(presented.encode(), secret.encode())


def render() -> tuple[bytes, str]:
    """The exposition text and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
