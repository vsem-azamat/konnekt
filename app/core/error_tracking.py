"""Errors to Sentry, without the data they happened to.

Only error-level logs and uncaught exceptions become events, under the event's
name (the same one the alert in the report chat carries). A rendered log line
can hold a person's text, a token in a URL or someone's phone number, so it is
never the message; warnings go along as breadcrumbs, by name only.

What the SDK collects by itself, request headers, URLs and the breadcrumbs of
outgoing HTTP calls among it, passes through `_scrub` before it leaves: the bot
token sits in every Bot API URL, and a Mini App request carries initData.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration
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
# a bearer or `tma <initData>` credential, signed initData itself, a phone number.
_PATTERNS = (
    re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"(?i)\b(bearer|tma)\s+\S+"),
    re.compile(r"(?:tgWebAppData|init_?data)=\S+", re.IGNORECASE),
    re.compile(r"\S*auth_date=\S*hash=\S*|\S*hash=\S*auth_date=\S*"),
    re.compile(r"\+\d[\d ()-]{7,}\d"),
)


def _scrub(value: Any) -> Any:
    """The same structure, with every string pattern-filtered."""
    if isinstance(value, str):
        for pattern in _PATTERNS:
            value = pattern.sub(_FILTERED, value)
        return value
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _before_send(event: Event, _hint: Hint) -> Event | None:
    return _scrub(event)


def _before_breadcrumb(crumb: Breadcrumb, _hint: Hint) -> Breadcrumb | None:
    return _scrub(crumb)


class SentryLogHandler(logging.Handler):
    """Errors as events and warnings as breadcrumbs, named by their event."""

    def __init__(self, *, process: str) -> None:
        super().__init__(level=logging.WARNING)
        self.process = process

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("sentry_sdk"):
            return
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
        before_breadcrumb=_before_breadcrumb,
        # The SDK's own log capture would send the rendered line; ours sends the name.
        integrations=[LoggingIntegration(level=None, event_level=None)],
    )
    handler = SentryLogHandler(process=process)
    for name in ("", *WATCHED_LOGGERS):
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if isinstance(h, SentryLogHandler)]:
            logger.removeHandler(old)
        logger.addHandler(handler)
    return True
