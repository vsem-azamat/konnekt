"""Telegram Mini App ``initData`` signature verification.

Contract (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):

  1. data_check_string = "\\n".join(sorted(f"{k}={v}")) over every received
     field except ``hash``
  2. secret = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
  3. compare HMAC_SHA256(key=secret, msg=data_check_string) against ``hash``
  4. reject a stale ``auth_date``

Two things catch people out here, and this module has been caught by both.

Step 2: Telegram's other browser flow, the Login Widget, derives its secret as
``sha256(bot_token)``; that widget is no longer used here, but the wrong
derivation is what anybody reaching for a half-remembered snippet will write,
and it fails every signature.

Step 1: ``signature`` is a received field like any other and *is* covered by
the HMAC. It is dropped only from the third-party Ed25519 check-string, which
is a different algorithm for validating without the bot token and is not what
this module implements. Excluding it here excluded a field every client has
sent since Bot API 7.10 — so the digest was computed over a shorter string
than the one Telegram signed, and every genuine launch was refused.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from app.core.exceptions import DomainError
from app.core.time import utc_now

# An hour, where the catalog allows a day (catalog/.../core/security.py), and
# on purpose: here initData is exchanged once for a console session or answers
# a join check on the spot, so a fresh one is always to hand; the catalog uses
# it as its session for as long as the Mini App stays open. The two checks are
# held to the same signatures by tests/webapi/test_init_data_agrees_with_aiogram.py.
_DEFAULT_MAX_AGE_SECONDS = 3600
_CLOCK_SKEW_SECONDS = 300


class InitDataError(DomainError):
    """Raised when an initData payload fails verification."""


@dataclass(frozen=True)
class WebAppUser:
    """The caller, as attested by Telegram's signature."""

    user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    query_id: str | None
    start_param: str | None
    raw_user: dict[str, Any]
    # When Telegram signed this payload, naive UTC: the same for every request
    # one launch makes, so it names the launch.
    auth_date: datetime.datetime


def verify_init_data(
    raw: str,
    *,
    bot_token: str,
    max_age_seconds: int = _DEFAULT_MAX_AGE_SECONDS,
    now: datetime.datetime | None = None,
) -> WebAppUser:
    """Return the verified caller, or raise :class:`InitDataError`.

    Every failure is the same exception on purpose: which check failed is
    useful to an attacker probing the endpoint and useless to a legitimate
    client, whose payload is built by Telegram itself.
    """
    if not bot_token:
        # Deriving a secret from an empty token would still produce a valid
        # HMAC, so an unconfigured deployment would verify attacker-signed data.
        raise InitDataError("bot token not configured")
    if not raw:
        raise InitDataError("empty payload")

    fields = dict(parse_qsl(raw, keep_blank_values=True))
    claimed_hash = fields.pop("hash", None)
    if not claimed_hash:
        raise InitDataError("missing hash")

    # Everything that is left, `signature` included. Dropping a field here would
    # sign less than Telegram did.
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, claimed_hash):
        raise InitDataError("signature mismatch")

    _check_freshness(fields.get("auth_date"), max_age_seconds=max_age_seconds, now=now)

    return _read_user(fields)


def _check_freshness(auth_date: str | None, *, max_age_seconds: int, now: datetime.datetime | None) -> None:
    if auth_date is None:
        raise InitDataError("missing auth_date")
    try:
        issued = int(auth_date)
    except ValueError as err:
        raise InitDataError("auth_date not an integer") from err

    current = now or utc_now()
    age = (current - datetime.datetime.fromtimestamp(issued, tz=datetime.UTC).replace(tzinfo=None)).total_seconds()
    if age > max_age_seconds or age < -_CLOCK_SKEW_SECONDS:
        raise InitDataError("auth_date out of range")


def _read_user(fields: dict[str, str]) -> WebAppUser:
    try:
        user = json.loads(fields.get("user", ""))
    except (json.JSONDecodeError, TypeError) as err:
        raise InitDataError("user field is not JSON") from err
    if not isinstance(user, dict) or "id" not in user:
        raise InitDataError("user field has no id")

    try:
        user_id = int(user["id"])
    except (TypeError, ValueError) as err:
        raise InitDataError("user id not an integer") from err

    return WebAppUser(
        user_id=user_id,
        first_name=str(user.get("first_name", "")),
        last_name=user.get("last_name"),
        username=user.get("username"),
        query_id=fields.get("query_id"),
        start_param=fields.get("start_param"),
        raw_user=user,
        # Checked to be an integer by _check_freshness before this runs.
        auth_date=datetime.datetime.fromtimestamp(int(fields["auth_date"]), tz=datetime.UTC).replace(tzinfo=None),
    )
