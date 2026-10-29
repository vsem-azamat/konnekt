"""Time utilities for consistent datetime handling."""

import datetime


def utc_now() -> datetime.datetime:
    """Return current UTC time as a naive datetime (no tzinfo).

    PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns require naive datetimes.
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def as_naive_utc(moment: datetime.datetime) -> datetime.datetime:
    """An aware time, such as Telegram's, as these columns store it."""
    return moment.astimezone(datetime.UTC).replace(tzinfo=None)
