"""Writing down what the Mini App said it did."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from app.db.models import ProductEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.usage.events import Event

# How far the client's clock is believed. A batch waits on the phone while the
# app is put away, so the past reaches as far as the signature does; the future
# is only a clock a little ahead.
PAST = datetime.timedelta(hours=24)
FUTURE = datetime.timedelta(minutes=1)


def when(at_ms: int, *, now: datetime.datetime) -> datetime.datetime:
    """The client's time, or the server's when the client's cannot be right."""
    at = datetime.datetime.fromtimestamp(at_ms / 1000, datetime.UTC).replace(tzinfo=None)
    return at if now - PAST <= at <= now + FUTURE else now


def write(
    db: AsyncSession,
    *,
    user_id: int,
    events: list[Event],
    platform: str,
    version: str,
    source: str | None,
    now: datetime.datetime,
) -> None:
    """Add the events of one batch; the caller commits.

    `source` is the start parameter Telegram signed for this launch. It goes on
    the launch's own `session_start`, never one the app sent after a break:
    the launch is what a link brought.
    """
    for event in events:
        props = dict(event.props)
        if event.name == "session_start" and not props.get("resumed") and source:
            props["source"] = source
        db.add(
            ProductEvent(
                user_id=user_id,
                session=event.session,
                seq=event.seq,
                name=event.name,
                screen=event.screen,
                props=props,
                at=when(event.at, now=now),
                platform=platform,
                version=version,
            )
        )
