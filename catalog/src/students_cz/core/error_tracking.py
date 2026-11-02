"""Errors to Sentry, without the data they happened to.

A log call here names its event in the message and puts the data in
`extra={"fields": ...}`; the fields stay on the host. What the SDK collects by
itself, headers, URLs and the breadcrumbs of outgoing calls, passes through
`_scrub` first: the bot token is in every Bot API URL, and a Mini App request
carries `Authorization: tma <initData>`.
"""

import logging
import re
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
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

# A bot token, a bearer or `tma` credential, signed initData, a phone number.
_PATTERNS = (
    re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"(?i)\b(bearer|tma)\s+\S+"),
    re.compile(r"(?:tgWebAppData|init_?data)=\S+", re.IGNORECASE),
    re.compile(r"\S*auth_date=\S*hash=\S*|\S*hash=\S*auth_date=\S*"),
    re.compile(r"\+\d[\d ()-]{7,}\d"),
)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _PATTERNS:
            value = pattern.sub(_FILTERED, value)
        return value
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def _before_send(event: Any, _hint: Any) -> Any:
    return _scrub(event)


def _before_breadcrumb(crumb: Any, _hint: Any) -> Any:
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
        before_breadcrumb=_before_breadcrumb,
        # Warnings as breadcrumbs, errors as events; the message is the event name.
        integrations=[LoggingIntegration(event_level=logging.ERROR)],
    )
    return True
