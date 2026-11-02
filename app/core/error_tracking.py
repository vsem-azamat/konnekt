"""Errors to Sentry, without the data they happened to.

Only error-level logs and uncaught exceptions become events, under the event's
name (the same one the alert in the report chat carries). A rendered log line
can hold a person's text, a token in a URL or someone's phone number, so it is
never the message; warnings go along as breadcrumbs, by name only.

What the SDK collects by itself passes through `_scrub` before it leaves: the
bot token sits in every Bot API URL, a Mini App request carries initData, and
a path or a query names the person it is about. A request goes with its
method and its address cut to the route, ids out; headers, query and body stay
behind. An exception's own message does go, filtered by the same patterns: it
is written by code, but a database error quotes the values it refused.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import sentry_sdk
import structlog
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from app.core.alerts import WATCHED_LOGGERS, event_of
from app.core.config import settings
from app.core.logging import EXCEPTION_ATTR

if TYPE_CHECKING:
    from sentry_sdk.types import Breadcrumb, Event, Hint

# Keys whose value is dropped wherever they appear in an event.
_DENYLIST = [
    *DEFAULT_DENYLIST,
    "init_data",
    "initdata",
    "tgwebappdata",
    "hash",
    "phone",
    "phone_number",
    "dsn",
]

_FILTERED = "[Filtered]"

# What a value can carry under any key: a bot token (in every Bot API URL),
# a bearer or `tma <initData>` credential, signed initData itself, a phone
# number, and the values a database error quotes.
_PATTERNS = (
    (re.compile(r"(?<!\d)\d{5,}:[A-Za-z0-9_-]{30,}"), _FILTERED),
    (re.compile(r"(?i)\b(bearer|tma)\s+\S+"), _FILTERED),
    (re.compile(r"(?:tgWebAppData|init_?data)=\S+", re.IGNORECASE), _FILTERED),
    (re.compile(r"\+\d[\d ()-]{7,}\d"), _FILTERED),
    # A database error's DETAIL line quotes the row; validation errors their input.
    # A value can span lines, or hold "HINT:": the DETAIL runs to the last HINT or SQL line.
    (re.compile(r"DETAIL:.*(?=\n(?:HINT:|\[SQL: ))|DETAIL:.*", re.DOTALL), f"DETAIL: {_FILTERED}"),
    (re.compile(r"input_value=.*(?=, input_type=)|input_value=.*"), f"input_value={_FILTERED}"),
    # FastAPI writes one error a line, its input (and ctx) to the end of it.
    (re.compile(r"'input': .*"), f"'input': {_FILTERED}"),
    # An address keeps its path, without the query or fragment after it...
    (re.compile(r"(?<![a-z0-9+.-])([a-z][a-z0-9+.-]*+://[^\s?#]*+)(?:[?#]\S*+)?", re.IGNORECASE), r"\1"),
    # ...and a long number in it is somebody's id.
    (re.compile(r"(?<=/)-?\d{5,}(?=[/\s]|$)"), ":id"),
)

# The event's own ids, which a pattern must not touch: a commit can hold a run of digits.
_OWN_KEYS = frozenset({"event_id", "release", "dist", "trace_id", "span_id", "parent_span_id"})

# What a request keeps; headers, cookies, query and body name the person.
_REQUEST_KEYS = ("method", "url")

# Breadcrumb data that is a query string, by another name.
_QUERY_KEYS = ("http.query", "http.fragment")


_TOKEN = re.compile(r"\S+")


def _signed_init_data(token: re.Match[str]) -> str:
    """initData in any spelling: a token carrying both its date and its signature.

    By token rather than by one pattern, which took seconds on a long value.
    """
    text = token.group()
    return _FILTERED if "auth_date=" in text and "hash=" in text else text


def _scrub(value: Any, key: str | None = None) -> Any:
    """The same structure, with every string pattern-filtered."""
    if isinstance(value, str):
        if key in _OWN_KEYS:
            return value
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return _TOKEN.sub(_signed_init_data, value)
    if isinstance(value, dict):
        return {name: _scrub(item, name) for name, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _named_by_route(request: Any, event: Any) -> Any:
    """The address as its route, `/avatars/{file_id}`, when the framework named it."""
    route = event.get("transaction")
    source = (event.get("transaction_info") or {}).get("source")
    url = request.get("url")
    if source == "route" and isinstance(route, str) and route.startswith("/") and isinstance(url, str):
        origin = re.match(r"[a-z][a-z0-9+.-]*://[^/?#]*", url, re.IGNORECASE)
        if origin:
            return {**request, "url": origin.group(0) + route}
    return request


def _before_send(event: Event, _hint: Hint) -> Event | None:
    request = event.get("request")
    if request:
        request = _named_by_route(request, event)
        event["request"] = {key: request[key] for key in _REQUEST_KEYS if key in request}
    return _scrub(event)


def _before_breadcrumb(crumb: Breadcrumb, _hint: Hint) -> Breadcrumb | None:
    data = crumb.get("data")
    if data:
        crumb["data"] = {key: item for key, item in data.items() if key not in _QUERY_KEYS}
    return _scrub(crumb)


# Set on a record once it is reported: uvicorn's error logger can reach the
# handler both directly and through the root.
_REPORTED = "_sentry_reported"


class SentryLogHandler(logging.Handler):
    """Errors as events and warnings as breadcrumbs, named by their event."""

    def __init__(self, *, process: str) -> None:
        super().__init__(level=logging.WARNING)
        self.process = process

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("sentry_sdk") or getattr(record, _REPORTED, False):
            return
        setattr(record, _REPORTED, True)
        try:
            name = event_of(record)
            if record.levelno < logging.ERROR:
                sentry_sdk.add_breadcrumb(category=record.name, message=name, level=record.levelname.lower())
                return
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("logger", record.name)
                scope.set_tag("process", self.process)
                # Ids only: what the update or request in hand bound (update,
                # chat, handler, request), never a person's details.
                for key, value in structlog.contextvars.get_contextvars().items():
                    scope.set_tag(key, str(value))
                level = "fatal" if record.levelno >= logging.CRITICAL else "error"
                exc_info = getattr(record, EXCEPTION_ATTR, None) or record.exc_info
                if exc_info and exc_info[1] is not None:
                    scope.set_extra("log_event", name)
                    scope.level = level
                    sentry_sdk.capture_exception(exc_info)
                else:
                    sentry_sdk.capture_message(name, level=level)
        except Exception:
            self.handleError(record)


def setup_error_tracking(process: str) -> bool:
    """Start reporting to Sentry when a DSN is set; say whether it did."""
    dsn = settings.sentry.dsn.get_secret_value()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry.environment or settings.environment,
        release=settings.sentry.release or None,
        sample_rate=settings.sentry.sample_rate,
        traces_sample_rate=settings.sentry.traces_sample_rate,
        # No send_default_pii: unset is off, and setting it at all is deprecated.
        # Locals hold the message being moderated, the initData being checked.
        include_local_variables=False,
        max_request_body_size="never",
        event_scrubber=EventScrubber(denylist=_DENYLIST, recursive=True),
        before_send=_before_send,
        before_send_transaction=_before_send,
        before_breadcrumb=_before_breadcrumb,
        integrations=[
            # The SDK's own log capture would send the rendered line; ours sends the name.
            LoggingIntegration(level=None, event_level=None),
            # A 503 is an answer, the catalog being down or a retry asked for;
            # what nobody caught is still reported.
            StarletteIntegration(failed_request_status_codes=set()),
            FastApiIntegration(failed_request_status_codes=set()),
        ],
    )
    handler = SentryLogHandler(process=process)
    for name in ("", *WATCHED_LOGGERS):
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if isinstance(h, SentryLogHandler)]:
            logger.removeHandler(old)
        logger.addHandler(handler)
    return True
