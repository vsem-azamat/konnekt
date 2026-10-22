"""Who hears about a request, when, and how often.

Against the seeded catalog, which also holds demo helpers and requests: every
assertion looks only at the people and requests its test made.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    HelperProfile,
    HelpRequest,
    Offer,
    RequestResponse,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import RequestStatus, UiLang
from students_cz.services import request_alerts
from students_cz.services.notify import Notifier, Recipient
from students_cz.services.request_alerts import PRAGUE, tick

pytestmark = pytest.mark.asyncio

# A weekday morning in Prague, well clear of the quiet hours.
MORNING = datetime(2026, 10, 22, 10, 0, tzinfo=PRAGUE)


class Watching(Notifier):
    """Records what would have been sent, to whom."""

    def __init__(self) -> None:
        super().__init__(None)
        self.sent: list[tuple[int, int, str]] = []

    async def tell_of_request(
        self, recipient: Recipient, text: str, request_id: int
    ) -> bool:
        self.sent.append((recipient.tg_id, request_id, text))
        return True

    def to(self, user: User) -> list[int]:
        return [request_id for tg_id, request_id, _ in self.sent if tg_id == user.tg_id]


async def _ids(session: AsyncSession) -> tuple[int, int]:
    subject = await session.scalar(
        select(Subject.id).where(Subject.slug == "matematicka-analyza")
    )
    service = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "tutoring")
    )
    assert subject is not None and service is not None
    return subject, service


@pytest.fixture
def reachable_helper(session: AsyncSession, helper_factory):
    async def make(tg_id: int, **kwargs) -> User:
        user = await helper_factory(tg_id=tg_id, **kwargs)
        user.bot_started_at = MORNING - timedelta(days=30)
        await session.flush()
        return user

    return make


@pytest.fixture
def post(session: AsyncSession):
    async def make(
        author: User,
        *,
        at: datetime = MORNING - timedelta(minutes=10),
        text: str = "нужен матан к зачёту",
        budget: float | None = None,
    ) -> HelpRequest:
        subject, service = await _ids(session)
        request = HelpRequest(
            author_id=author.id,
            raw_text=text,
            subject_id=subject,
            service_type_id=service,
            budget_max=budget,
            status=RequestStatus.OPEN,
            created_at=at,
        )
        session.add(request)
        await session.flush()
        return request

    return make


async def _student(session: AsyncSession, tg_id: int) -> User:
    user = User(tg_id=tg_id, first_name="Student", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()
    return user


async def test_a_helper_hears_once_in_their_language(
    session: AsyncSession, reachable_helper, post
) -> None:
    helper = await reachable_helper(95001)
    helper.ui_lang = UiLang.EN
    request = await post(
        await _student(session, 95002), text="calculus <3 before the exam", budget=500
    )
    watcher = Watching()

    await tick(session, watcher, MORNING)
    await tick(session, watcher, MORNING + timedelta(minutes=1))

    assert watcher.to(helper) == [request.id]
    [text] = [text for tg_id, _, text in watcher.sent if tg_id == helper.tg_id]
    assert text.startswith("<b>A new request for your service</b>")
    assert "calculus &lt;3 before the exam" in text
    assert "Budget up to 500 Kč" in text
    assert "“My services”" in text


async def test_nothing_in_the_first_five_minutes(
    session: AsyncSession, reachable_helper, post
) -> None:
    helper = await reachable_helper(95011)
    request = await post(
        await _student(session, 95012), at=MORNING - timedelta(minutes=4)
    )
    watcher = Watching()

    await tick(session, watcher, MORNING)
    assert watcher.to(helper) == []

    await tick(session, watcher, MORNING + timedelta(minutes=1))
    assert watcher.to(helper) == [request.id]


async def test_the_night_waits_for_the_morning(
    session: AsyncSession, reachable_helper, post
) -> None:
    helper = await reachable_helper(95021)
    evening = datetime(2026, 10, 21, 21, 58, tzinfo=PRAGUE)
    request = await post(await _student(session, 95022), at=evening)
    watcher = Watching()

    await tick(session, watcher, evening + timedelta(minutes=10))
    await tick(session, watcher, datetime(2026, 10, 22, 7, 59, tzinfo=PRAGUE))
    assert watcher.to(helper) == []

    await tick(session, watcher, datetime(2026, 10, 22, 8, 0, tzinfo=PRAGUE))
    assert watcher.to(helper) == [request.id]


async def test_who_is_not_told(
    session: AsyncSession, reachable_helper, helper_factory, post
) -> None:
    author = await reachable_helper(95031)
    never_started = await helper_factory(tg_id=95032)
    switched_off = await reachable_helper(95033)
    unsubscribed = await reachable_helper(95034)
    paused = await reachable_helper(95035)
    answered = await reachable_helper(95036)
    other_subject = await reachable_helper(95037, subject_slug="linearni-algebra")
    told = await reachable_helper(95038)

    (await session.get(HelperProfile, switched_off.id)).new_request_alerts = False  # ty: ignore[invalid-assignment]
    unsubscribed.unsubscribed_at = MORNING - timedelta(days=1)
    for offer in await session.scalars(select(Offer).where(Offer.helper_id == paused.id)):
        offer.is_active = False
    request = await post(author)
    session.add(
        RequestResponse(request_id=request.id, helper_id=answered.id, message="могу")
    )
    await session.flush()
    watcher = Watching()

    await tick(session, watcher, MORNING)

    for nobody in (
        author,
        never_started,
        switched_off,
        unsubscribed,
        paused,
        answered,
        other_subject,
    ):
        assert watcher.to(nobody) == [], nobody.tg_id
    assert watcher.to(told) == [request.id]


async def test_a_closed_request_is_not_announced(
    session: AsyncSession, reachable_helper, post
) -> None:
    helper = await reachable_helper(95041)
    request = await post(await _student(session, 95042))
    request.status = RequestStatus.CLOSED
    await session.flush()
    watcher = Watching()

    await tick(session, watcher, MORNING)

    assert watcher.to(helper) == []


async def test_five_a_day_and_the_rest_tomorrow(
    session: AsyncSession, reachable_helper, post
) -> None:
    helper = await reachable_helper(95051)
    student = await _student(session, 95052)
    requests = [
        await post(student, at=MORNING - timedelta(minutes=30 - minute))
        for minute in range(request_alerts.DAILY_LIMIT + 1)
    ]
    watcher = Watching()

    await tick(session, watcher, MORNING)
    await tick(session, watcher, MORNING + timedelta(hours=11))
    # The oldest first: they have waited longest.
    assert watcher.to(helper) == [r.id for r in requests[: request_alerts.DAILY_LIMIT]]

    await tick(session, watcher, MORNING + timedelta(hours=22))
    assert watcher.to(helper)[-1] == requests[-1].id


async def test_the_switch_is_saved_with_the_profile(client, helper_factory) -> None:
    from .conftest import auth_header

    await helper_factory(tg_id=95061)
    headers = auth_header(95061)

    assert (await client.get("/api/v1/helper", headers=headers)).json()[
        "new_request_alerts"
    ] is True

    off = await client.put(
        "/api/v1/helper",
        json={"new_request_alerts": False, "publish": True},
        headers=headers,
    )
    assert off.status_code == 200, off.text
    assert (await client.get("/api/v1/helper", headers=headers)).json()[
        "new_request_alerts"
    ] is False

    # A screen that does not carry it leaves it as it was.
    await client.put("/api/v1/helper", json={"publish": True}, headers=headers)
    assert (await client.get("/api/v1/helper", headers=headers)).json()[
        "new_request_alerts"
    ] is False
