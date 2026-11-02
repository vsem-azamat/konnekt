"""Errors to Sentry, without the data they happened to.

A log call here names its event in the message and puts the data in
`extra={"fields": ...}`; the fields stay on the host. What the SDK collects by
itself, headers, URLs and the breadcrumbs of outgoing calls, passes through
`_scrub` first: the bot token is in every Bot API URL, a Mini App request
carries `Authorization: tma <initData>`, and a path or a query names the
person it is about. A request goes with its method and its address cut to the
route, ids out; headers, query and body stay behind.
"""

import logging
import re
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from students_cz.core.config import Settings

_DENYLIST = [
    *DEFAULT_DENYLIST,
    "init_data",
    "initdata",
    "tgwebappdata",
    "hash",
    "phone",
    "phone_number",
    "dsn",
    "fields",
]

_FILTERED = "[Filtered]"

# A bot token, a bearer or `tma` credential, signed initData, a phone number,
# the values a database error quotes; an address loses its query and the ids
# in its path.
_PATTERNS = (
    (re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}"), _FILTERED),
    (re.compile(r"(?i)\b(bearer|tma)\s+\S+"), _FILTERED),
    (re.compile(r"(?:tgWebAppData|init_?data)=\S+", re.IGNORECASE), _FILTERED),
    (re.compile(r"\S*auth_date=\S*hash=\S*|\S*hash=\S*auth_date=\S*"), _FILTERED),
    (re.compile(r"\+\d[\d ()-]{7,}\d"), _FILTERED),
    (re.compile(r"(Key \([^)]*\))=\([^)]*\)"), rf"\1=({_FILTERED})"),
    (re.compile(r"([a-z][a-z0-9+.-]*://[^\s?#]*)[?#]\S*", re.IGNORECASE), r"\1"),
    (re.compile(r"(?<=/)-?\d{5,}(?=[/\s]|$)"), ":id"),
)

# The event's own ids, which a pattern must not touch.
_OWN_KEYS = frozenset(
    {"event_id", "release", "dist", "trace_id", "span_id", "parent_span_id"}
)
_REQUEST_KEYS = ("method", "url")
_QUERY_KEYS = ("http.query", "http.fragment")


def _scrub(value: Any, key: str | None = None) -> Any:
    if isinstance(value, str):
        if key in _OWN_KEYS:
            return value
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {name: _scrub(item, name) for name, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _before_send(event: Any, _hint: Any) -> Any:
    request = event.get("request")
    if request:
        event["request"] = {key: request[key] for key in _REQUEST_KEYS if key in request}
    return _scrub(event)


def _before_breadcrumb(crumb: Any, _hint: Any) -> Any:
    data = crumb.get("data")
    if data:
        crumb["data"] = {
            key: item for key, item in data.items() if key not in _QUERY_KEYS
        }
    return _scrub(crumb)


def setup_error_tracking(settings: Settings) -> bool:
    """Start reporting when a DSN is set; say whether it did."""
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        sample_rate=settings.sentry_sample_rate,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # No send_default_pii: unset is off, and setting it at all is deprecated.
        # Locals hold the profile being saved, the initData being checked.
        include_local_variables=False,
        max_request_body_size="never",
        event_scrubber=EventScrubber(denylist=_DENYLIST, recursive=True),
        before_send=_before_send,
        before_send_transaction=_before_send,
        before_breadcrumb=_before_breadcrumb,
        integrations=[
            # Warnings as breadcrumbs, errors as events; the message is the event name.
            LoggingIntegration(event_level=logging.ERROR),
            # A 503 is an answer (search without its model, say); what nobody
            # caught is still reported.
            StarletteIntegration(failed_request_status_codes=set()),
            FastApiIntegration(failed_request_status_codes=set()),
        ],
    )
    return True
