"""Telling helpers that somebody posted a request they could answer.

The one message the bot sends that answers nothing its recipient did, so it
is kept rare and easy to stop:

* To exactly the people the request's «Заявку видят N помощников» counts (see
  `catalog.helpers_listed`), less those who cannot or would rather not be
  written to: everyone `people.reachable` leaves out, and whoever switched
  these off in «Мои услуги».
* Five minutes after posting, so a request deleted or closed straight away is
  never announced, and only while it can still be answered.
* Not at night in Prague. What falls due then waits until morning.
* At most `DAILY_LIMIT` a Prague day per helper, one a minute, and once per
  request: a request past the limit is still in their incoming list.

A loop inside the API process rather than a send from the endpoint, because
every one of those rules is about time. One row per message in
`request_alerts` is written before it is sent, and both the once-only rule and
the daily count read those rows.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.bot.texts import BUDGET_UP_TO, NEW_REQUEST_FOR_HELPER, pick
from students_cz.db.models import (
    HelperProfile,
    HelpRequest,
    RequestAlert,
    RequestResponse,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import UiLang
from students_cz.db.session import get_sessionmaker
from students_cz.services import catalog, people
from students_cz.services.naming import names_by_id
from students_cz.services.notify import Notifier, Recipient, money, quote
from students_cz.services.requests import live

log = logging.getLogger("students_cz.request_alerts")

PRAGUE = ZoneInfo("Europe/Prague")
# Long enough to delete a request posted by mistake, or fix its subject.
DELAY = timedelta(minutes=5)
DAILY_LIMIT = 5
QUIET_FROM = time(22)
QUIET_UNTIL = time(8)
# Wide enough for a request posted as the quiet hours begin to go out in the
# morning, and no wider: this is also how far back a helper who has just become
# reachable, or the first tick after a deploy, reaches. Older ones are not
# news, and a helper finds them in the list.
LOOKBACK = timedelta(hours=12)
EVERY_SECONDS = 60
# pg_try_advisory_xact_lock's key: one tick at a time, should two processes
# ever overlap during a deploy.
_LOCK_KEY = 0x5245_5141  # "REQA"


@dataclass(frozen=True)
class Alert:
    """One message owed, rendered while the session that loaded it is open."""

    request_id: int
    helper_id: int
    recipient: Recipient
    text: str


def quiet(now: datetime) -> bool:
    """Whether it is night in Prague, when nobody is written to."""
    local = now.astimezone(PRAGUE).time()
    return local >= QUIET_FROM or local < QUIET_UNTIL


def day_start(now: datetime) -> datetime:
    """Midnight in Prague on the day `now` falls on: where the allowance resets."""
    return datetime.combine(now.astimezone(PRAGUE).date(), time(), PRAGUE)


async def due(session: AsyncSession, now: datetime) -> list[Alert]:
    """Every message that should go out at `now`, oldest request first.

    Oldest first so that a helper at their limit has heard about the requests
    that have waited longest. One per helper: what is left goes on the next
    tick, so the morning after a busy night is a message a minute rather than
    a burst that runs into Telegram's flood limit.
    """
    if quiet(now):
        return []

    requests = (
        await session.scalars(
            select(HelpRequest)
            .where(
                live(now),
                HelpRequest.created_at <= now - DELAY,
                HelpRequest.created_at > now - LOOKBACK,
                # As `helpers_seeing`: a request naming neither has nobody.
                or_(
                    HelpRequest.subject_id.is_not(None),
                    HelpRequest.service_type_id.is_not(None),
                ),
            )
            .order_by(HelpRequest.created_at, HelpRequest.id)
        )
    ).all()
    if not requests:
        return []

    told_today: dict[int, int] = {
        helper_id: count
        for helper_id, count in await session.execute(
            select(RequestAlert.helper_id, func.count())
            .where(RequestAlert.created_at >= day_start(now))
            .group_by(RequestAlert.helper_id)
        )
    }

    alerts: list[Alert] = []
    this_tick: set[int] = set()
    for request in requests:
        listed = await catalog.helpers_listed(
            session,
            subject_id=request.subject_id,
            service_type_id=request.service_type_id,
            exclude_helper_id=request.author_id,
        )
        told = select(RequestAlert.helper_id).where(RequestAlert.request_id == request.id)
        answered = select(RequestResponse.helper_id).where(
            RequestResponse.request_id == request.id
        )
        helpers = (
            await session.scalars(
                people.reachable()
                .join(HelperProfile, HelperProfile.user_id == User.id)
                .where(
                    User.id.in_(listed),
                    User.id.not_in(told),
                    User.id.not_in(answered),
                    HelperProfile.new_request_alerts.is_(True),
                )
                .order_by(User.id)
            )
        ).all()

        texts: dict[UiLang, str] = {}
        for helper in helpers:
            if helper.id in this_tick or told_today.get(helper.id, 0) >= DAILY_LIMIT:
                continue
            this_tick.add(helper.id)
            told_today[helper.id] = told_today.get(helper.id, 0) + 1
            recipient = Recipient.of(helper)
            if recipient.lang not in texts:
                texts[recipient.lang] = await _text(session, request, recipient.lang)
            alerts.append(
                Alert(
                    request_id=request.id,
                    helper_id=helper.id,
                    recipient=recipient,
                    text=texts[recipient.lang],
                )
            )
    return alerts


async def tick(session: AsyncSession, notifier: Notifier, now: datetime) -> int:
    """Send what is due at `now`. Returns how many arrived.

    The rows are committed before anything is sent: a message lost on the way
    is not tried again, and one that went out is never sent twice.
    """
    if not await session.scalar(select(func.pg_try_advisory_xact_lock(_LOCK_KEY))):
        return 0
    alerts = await due(session, now)
    for alert in alerts:
        session.add(
            RequestAlert(
                request_id=alert.request_id,
                helper_id=alert.helper_id,
                created_at=now,
            )
        )
    await session.commit()

    sent = 0
    for alert in alerts:
        if await notifier.tell_of_request(alert.recipient, alert.text, alert.request_id):
            sent += 1
    return sent


async def run(notifier: Notifier) -> None:
    """Tick once a minute for as long as the process lives.

    A failed tick is logged and the next one tried: nothing it would have sent
    is lost, because nothing was recorded as sent.
    """
    while True:
        try:
            async with get_sessionmaker()() as session:
                await tick(session, notifier, datetime.now(UTC))
        except Exception:
            log.exception("request alerts: tick failed")
        await asyncio.sleep(EVERY_SECONDS)


async def _text(session: AsyncSession, request: HelpRequest, lang: UiLang) -> str:
    """The message, in the helper's language: the kind of help and the subject
    by our names for them, then the request in the author's own words."""
    service = (
        await names_by_id(session, ServiceType, [request.service_type_id], lang)
        if request.service_type_id
        else {}
    )
    subject = (
        await names_by_id(session, Subject, [request.subject_id], lang)
        if request.subject_id
        else {}
    )
    topic = " · ".join(
        name
        for name in (
            service.get(request.service_type_id or 0),
            subject.get(request.subject_id or 0),
        )
        if name
    )
    budget = (
        pick(BUDGET_UP_TO, lang).format(
            amount=money(request.budget_max, request.budget_currency)
        )
        if request.budget_max is not None
        else ""
    )
    return pick(NEW_REQUEST_FOR_HELPER, lang).format(
        topic=quote(topic, 120),
        text=quote(request.raw_text),
        budget=budget,
    )
