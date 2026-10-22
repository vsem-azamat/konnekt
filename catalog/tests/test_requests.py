"""The other direction: a student asks, a helper answers.

The catalog side is tested in test_api; this covers the loop that only exists
once someone can reply — who may see incoming requests, who may answer them,
and what the author sees afterwards.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    Contact,
    HelperProfile,
    HelpRequest,
    RequestResponse,
    User,
)
from students_cz.db.models.enums import PublishStatus, RequestStatus

from .conftest import app_for, auth_header

STUDENT = 90501
HELPER = 90502
OTHER = 90503

pytestmark = pytest.mark.asyncio


def helper_header(tg_id: int = HELPER, **extra) -> dict[str, str]:
    """A helper, with the public username answering a request now requires."""
    return auth_header(tg_id, username=f"helper{tg_id}", **extra)


async def post_request(client: AsyncClient, text: str, tg_id: int = STUDENT) -> dict:
    response = await client.post(
        "/api/v1/requests", json={"text": text}, headers=auth_header(tg_id)
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── who may look ────────────────────────────────────────────────────────


async def test_feed_refuses_someone_with_no_profile(client: AsyncClient) -> None:
    response = await client.get("/api/v1/requests/feed", headers=auth_header(OTHER))
    assert response.status_code == 403


async def test_draft_helper_may_look_but_not_answer(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Seeing the demand is the argument for finishing the profile."""
    created = await post_request(client, "нужна помощь с матаном, ЧВУТ")
    helper = await helper_factory(tg_id=HELPER)
    profile = await session.get(HelperProfile, helper.id)
    assert profile is not None
    profile.status = PublishStatus.DRAFT
    await session.commit()

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert feed.status_code == 200
    assert created["id"] in [item["id"] for item in feed.json()]

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 403


async def test_feed_hides_your_own_requests(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    mine = await post_request(client, "ищу помощь с матаном", tg_id=HELPER)

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert mine["id"] not in [item["id"] for item in feed.json()]


async def test_feed_ranks_your_subject_first_and_says_why(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A request about what you teach outranks one posted more recently."""
    await helper_factory(tg_id=HELPER, subject_slug="matematicka-analyza")
    on_subject = await post_request(client, "матан ЧВУТ, экзамен через неделю")
    # Posted after, so only relevance can put the other one first.
    await post_request(client, "нужен фотограф на выпускной")

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert feed[0]["id"] == on_subject["id"]
    assert feed[0]["reason"]["code"] == "feed.same_subject"
    # The author is shown; who else is bidding is not.
    assert feed[0]["author_name"]
    assert "responders" not in feed[0] or feed[0]["responders"] == []


async def test_feed_keeps_a_request_you_already_answered_marked(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан, нужна помощь")

    answered = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "помогу, готовил к этому экзамену"},
        headers=helper_header(),
    )
    assert answered.status_code == 201, answered.text

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [item] = [item for item in feed if item["id"] == created["id"]]
    assert item["responded"] is True


async def test_feed_hides_closed_requests(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан срочно")
    await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert created["id"] not in [item["id"] for item in feed]


# ── answering ───────────────────────────────────────────────────────────


async def test_answering_shows_up_for_the_author(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER, first_name="Marek")
    created = await post_request(client, "матан, ЧВУТ, экзамен 14 февраля")

    # The name comes from initData, not from our row: Telegram owns it, and
    # `remember` overwrites what the fixture invented on every call.
    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "готовил к этому экзамену, могу помочь", "price_amount": 500},
        headers=helper_header(first_name="Marek"),
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["price"]["amount"] == 500
    assert answer.json()["status"] == "sent"

    listed = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert listed.status_code == 200
    [row] = listed.json()
    assert row["name"].startswith("Marek")
    assert row["message"].startswith("готовил")

    mine = (await client.get("/api/v1/requests", headers=auth_header(STUDENT))).json()
    assert mine[0]["responses_count"] == 1


async def test_reading_the_answers_marks_them_read(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь с этим"},
        headers=helper_header(),
    )

    first = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert first.json()[0]["status"] == "sent"

    second = await client.get(
        f"/api/v1/requests/{created['id']}/responses", headers=auth_header(STUDENT)
    )
    assert second.json()[0]["status"] == "read"


async def test_answering_twice_is_refused(client: AsyncClient, helper_factory) -> None:
    """One answer per helper. Repeat pitching is spam."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    body = {"message": "могу помочь с матаном"}

    first = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json=body,
        headers=helper_header(),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json=body,
        headers=helper_header(),
    )
    assert second.status_code == 409


async def test_answering_your_own_request_is_refused(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    mine = await post_request(client, "матан", tg_id=HELPER)

    answer = await client.post(
        f"/api/v1/requests/{mine['id']}/respond",
        json={"message": "сам себе помогу"},
        headers=helper_header(),
    )
    assert answer.status_code == 400


async def test_answering_a_closed_request_is_refused(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 409


async def test_an_expired_request_cannot_be_answered(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Open but past its deadline is closed in every way that matters."""
    from datetime import UTC, datetime, timedelta

    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан, экзамен завтра")
    request = await session.get(HelpRequest, created["id"])
    assert request is not None
    request.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    assert created["id"] not in [item["id"] for item in feed]

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 409


# ── the author's side ───────────────────────────────────────────────────


async def test_answers_are_not_a_public_bid_list(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )

    # Not the author, and not even the helper who answered.
    for tg_id in (OTHER, HELPER):
        peeking = await client.get(
            f"/api/v1/requests/{created['id']}/responses", headers=auth_header(tg_id)
        )
        assert peeking.status_code == 404


async def test_accepting_records_a_contact_and_leaves_the_request_open(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    helper = await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    accepted = await client.post(
        f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    student = await session.scalar(select(User).where(User.tg_id == STUDENT))
    assert student is not None
    contact = await session.scalar(
        select(Contact).where(
            Contact.student_id == student.id, Contact.helper_id == helper.id
        )
    )
    assert contact is not None
    assert contact.request_id == created["id"]

    # Needing two people for two subjects is ordinary.
    request = await session.get(HelpRequest, created["id"])
    assert request is not None
    await session.refresh(request)
    assert request.status is RequestStatus.OPEN


async def test_only_the_author_may_accept(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    for tg_id in (OTHER, HELPER):
        stolen = await client.post(
            f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(tg_id)
        )
        assert stolen.status_code == 404


async def test_declining(client: AsyncClient, helper_factory) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = (
        await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь"},
            headers=helper_header(),
        )
    ).json()

    declined = await client.post(
        f"/api/v1/responses/{answer['id']}/decline", headers=auth_header(STUDENT)
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"


# ── what the review of this feature turned up ───────────────────────────


async def _answer(client: AsyncClient, request_id: int, tg_id: int = HELPER) -> dict:
    response = await client.post(
        f"/api/v1/requests/{request_id}/respond",
        json={"message": "могу помочь с этим"},
        headers=helper_header(tg_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_banned_profile_cannot_read_the_feed(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """The feed is names, faces and budgets — a target list for a banned account."""
    await post_request(client, "матан, ЧВУТ")
    helper = await helper_factory(tg_id=HELPER)
    profile = await session.get(HelperProfile, helper.id)
    assert profile is not None
    profile.status = PublishStatus.BANNED
    await session.commit()

    feed = await client.get("/api/v1/requests/feed", headers=helper_header())
    assert feed.status_code == 403


async def test_answering_needs_a_public_username(
    client: AsyncClient, helper_factory
) -> None:
    """Without one the author has nowhere to write, so the deal is a dead end."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        # No username in the init data.
        headers=auth_header(HELPER),
    )
    assert answer.status_code == 409
    assert "username" in answer.json()["detail"]


async def test_a_blank_answer_is_refused(client: AsyncClient, helper_factory) -> None:
    """min_length sees the raw string; "   " would be stored as an empty message."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")

    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "     "},
        headers=helper_header(),
    )
    assert answer.status_code == 422


async def test_accepting_twice_records_one_contact(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """A double tap must not invent a second deal, or a second notification."""
    helper = await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = await _answer(client, created["id"])

    for _ in range(3):
        accepted = await client.post(
            f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"

    student = await session.scalar(select(User).where(User.tg_id == STUDENT))
    assert student is not None
    contacts = await session.scalar(
        select(func.count(Contact.id)).where(
            Contact.student_id == student.id, Contact.helper_id == helper.id
        )
    )
    assert contacts == 1


async def test_an_accepted_answer_cannot_be_declined(
    client: AsyncClient, helper_factory
) -> None:
    """Otherwise the author reads "declined" while the helper reads "chosen"."""
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = await _answer(client, created["id"])

    await client.post(
        f"/api/v1/responses/{answer['id']}/accept", headers=auth_header(STUDENT)
    )
    declined = await client.post(
        f"/api/v1/responses/{answer['id']}/decline", headers=auth_header(STUDENT)
    )
    assert declined.status_code == 409


async def test_the_feed_does_not_say_how_many_others_answered(
    client: AsyncClient, helper_factory
) -> None:
    """A helper who can see "already contested" simply skips those."""
    await helper_factory(tg_id=HELPER)
    await helper_factory(tg_id=OTHER, first_name="Petra")
    created = await post_request(client, "матан")
    await _answer(client, created["id"], tg_id=OTHER)

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [row] = [item for item in feed if item["id"] == created["id"]]
    assert "responses_count" not in row
    assert "responders" not in row


# ── the request is one transaction ──────────────────────────────────────


async def test_a_failure_after_the_write_leaves_nothing_behind(
    client: AsyncClient, session: AsyncSession, helper_factory, monkeypatch
) -> None:
    """Answering a request is all of it or none of it.

    The row is written first and the notification to the author is composed
    afterwards, so a failure in between used to leave an answer nobody was
    told about — the helper saw a 500 and assumed it had not gone through.
    """
    from students_cz.api.v1 import requests as requests_api

    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")

    def explode(*args, **kwargs):
        raise RuntimeError("rendering the notification blew up")

    # Rendering the answer, which happens after the row is written and before
    # the notification is composed from it — the window the rule is about.
    monkeypatch.setattr(requests_api, "_responses_out", explode)

    # A 500: the server-error middleware answers, and RequestLog, outside it,
    # reports the failure without handing it on to the server a second time.
    response = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь с этим"},
        headers=helper_header(),
    )
    assert response.status_code == 500

    answered = await session.scalar(
        select(func.count())
        .select_from(RequestResponse)
        .where(RequestResponse.request_id == created["id"])
    )
    assert answered == 0


# ── the notification ────────────────────────────────────────────────────


class RecordingBot:
    """A bot that keeps what it was asked to send.

    Enough of aiogram's `Bot` for `notify.tell`, which calls exactly one
    method on it. The point of the tests below is the wiring between the route
    and the person, so what matters is that a message arrived and who it was
    addressed to.

    Do not teach it to raise `TelegramForbiddenError`: `tell` answers that by
    opening a session of its own and updating the row, and the row is inside
    this test's uncommitted transaction — so it would wait on the lock until
    the suite is killed rather than fail.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


async def test_the_author_hears_about_an_answer(
    session: AsyncSession, helper_factory
) -> None:
    """End to end through the dependency, not through a helper function.

    The route asks for a notifier and the notifier reaches for the bot the
    process was started with. Nothing between the two is mocked here, so this
    is the test that fails if the wiring is wrong — the unit tests around
    `Notifier` would all still pass with the route never calling it.
    """
    bot = RecordingBot()
    transport = ASGITransport(app=app_for(session, bot=bot))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await helper_factory(tg_id=HELPER)
        created = await post_request(client, "матан")

        # Somebody who reached the app through a link has never messaged the
        # bot, and Telegram would answer 403. Say they have.
        author = await session.scalar(select(User).where(User.tg_id == STUDENT))
        assert author is not None
        author.bot_started_at = datetime.now(UTC)
        await session.flush()

        response = await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь с этим"},
            headers=helper_header(),
        )

    assert response.status_code == 201, response.text
    assert [message["chat_id"] for message in bot.sent] == [STUDENT]
    assert "могу помочь с этим" in bot.sent[0]["text"]
    # The button is the one thing whose source this refactor moved: it used to
    # come off `app.state.settings`, which the test client never has, so it was
    # silently absent from every test. `PUBLIC_BASE_URL` is pinned in conftest
    # for exactly this assertion.
    [[button]] = bot.sent[0]["reply_markup"].inline_keyboard
    assert button.web_app is not None
    assert button.web_app.url == "https://tests.example"


async def test_nobody_hears_about_it_who_never_started_the_bot(
    session: AsyncSession, helper_factory
) -> None:
    """The control, at the same level.

    Without it the test above passes for any wiring that sends to everybody,
    and the reachability rule is exactly the one that keeps somebody from
    being recorded as having blocked a bot they never met.
    """
    bot = RecordingBot()
    transport = ASGITransport(app=app_for(session, bot=bot))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await helper_factory(tg_id=HELPER)
        created = await post_request(client, "матан")

        response = await client.post(
            f"/api/v1/requests/{created['id']}/respond",
            json={"message": "могу помочь с этим"},
            headers=helper_header(),
        )

    assert response.status_code == 201, response.text
    assert bot.sent == []


# ── what the text says, and what the caller says ────────────────────────


async def test_a_removed_chip_is_not_put_back_by_the_text(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The screen shows the parse back as chips; removing one has to mean it.

    Anything the caller leaves out is read out of the text — that is what lets
    the form be one field. But a caller who *said* «no institution» has said
    something, and the text saying ČVUT does not overrule them.
    """
    text = "матан на ČVUT FEL, экзамен 14 февраля"

    inferred = await client.post(
        "/api/v1/requests", json={"text": text}, headers=auth_header(STUDENT)
    )
    assert inferred.status_code == 201, inferred.text
    assert inferred.json()["institution"] is not None, "the text names a school"

    kept = await client.post(
        "/api/v1/requests",
        json={"text": text, "institution_id": None},
        headers=auth_header(OTHER),
    )
    assert kept.status_code == 201, kept.text
    assert kept.json()["institution"] is None, "a removed chip came back"


async def test_the_same_request_twice_is_one_request(client: AsyncClient) -> None:
    """A double tap, or a reload, is not a second thing to answer."""
    text = "нужен матан, экзамен 14 февраля"
    first = await client.post(
        "/api/v1/requests", json={"text": text}, headers=auth_header(STUDENT)
    )
    assert first.status_code == 201, first.text

    again = await client.post(
        "/api/v1/requests", json={"text": text}, headers=auth_header(STUDENT)
    )
    assert again.status_code == 409, again.text


async def test_two_different_errands_are_two_requests(client: AsyncClient) -> None:
    """Half the catalog has no subject, so two NULLs are not a match.

    A visa yesterday and a flat today are two things to answer, and a rule that
    reads them as one locks a person out of every request after their first.
    """
    first = await client.post(
        "/api/v1/requests",
        json={"text": "нужна помощь с оформлением визы"},
        headers=auth_header(STUDENT),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/requests",
        json={"text": "ищу жильё в Праге"},
        headers=auth_header(STUDENT),
    )
    assert second.status_code == 201, second.text


async def test_an_expired_request_does_not_block_asking_again(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Expiry is a deadline, not a job that has to have run.

    A request thirty-one days old still reads `open`, and is invisible in every
    feed and refuses answers. Letting it refuse the next ask leaves the person
    to hunt down a corpse before they can ask again.
    """
    posted = await post_request(client, "нужен матан")
    request = await session.get(HelpRequest, posted["id"])
    assert request is not None
    request.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.flush()

    again = await client.post(
        "/api/v1/requests", json={"text": "нужен матан"}, headers=auth_header(STUDENT)
    )
    assert again.status_code == 201, again.text


async def test_the_same_subject_at_two_schools_is_two_requests(
    client: AsyncClient,
) -> None:
    """Calculus at ČVUT and calculus at VŠE are two different asks."""
    first = await client.post(
        "/api/v1/requests",
        json={"text": "нужен матан на ČVUT FEL"},
        headers=auth_header(STUDENT),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/requests",
        json={"text": "нужен матан на VŠE"},
        headers=auth_header(STUDENT),
    )
    assert second.status_code == 201, second.text


async def test_two_errands_sharing_only_a_date_are_two_requests(
    client: AsyncClient,
) -> None:
    """A date is not an identity — exam week is the same week for everybody."""
    first = await client.post(
        "/api/v1/requests",
        json={"text": "срочно нужно закрыть долг к 14 февраля"},
        headers=auth_header(STUDENT),
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/requests",
        json={"text": "перевести документы к 14 февраля"},
        headers=auth_header(STUDENT),
    )
    assert second.status_code == 201, second.text


# ── closing and removing ────────────────────────────────────────────────


async def test_closing_says_when(client: AsyncClient) -> None:
    created = await post_request(client, "матан")
    assert created["closed_at"] is None

    closed = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )
    assert closed.json()["status"] == "closed"
    when = closed.json()["closed_at"]
    assert when is not None

    again = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )
    assert again.json()["closed_at"] == when


async def test_a_request_past_its_deadline_is_listed_as_expired(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = await post_request(client, "матан, экзамен завтра")
    request = await session.get(HelpRequest, created["id"])
    assert request is not None
    request.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    [mine] = (await client.get("/api/v1/requests", headers=auth_header(STUDENT))).json()
    assert mine["status"] == "expired"
    assert mine["expires_at"] is not None


async def test_deleting_removes_the_request_and_its_answers(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    created = await post_request(client, "матан")
    answer = await client.post(
        f"/api/v1/requests/{created['id']}/respond",
        json={"message": "могу помочь"},
        headers=helper_header(),
    )
    assert answer.status_code == 201, answer.text

    gone = await client.delete(
        f"/api/v1/requests/{created['id']}", headers=auth_header(STUDENT)
    )
    assert gone.status_code == 204

    mine = (await client.get("/api/v1/requests", headers=auth_header(STUDENT))).json()
    assert mine == []
    left = await session.scalar(
        select(func.count(RequestResponse.id)).where(
            RequestResponse.request_id == created["id"]
        )
    )
    assert left == 0


async def test_only_the_author_may_delete(client: AsyncClient) -> None:
    created = await post_request(client, "матан")

    refused = await client.delete(
        f"/api/v1/requests/{created['id']}", headers=auth_header(OTHER)
    )
    assert refused.status_code == 404
    mine = (await client.get("/api/v1/requests", headers=auth_header(STUDENT))).json()
    assert [item["id"] for item in mine] == [created["id"]]


# ── who could answer ────────────────────────────────────────────────────


async def _seeing_and_listed(client: AsyncClient, created: dict) -> tuple[int, int]:
    """The count on the request, and the total of the search shown under it."""
    [mine] = [
        item
        for item in (
            await client.get("/api/v1/requests", headers=auth_header(STUDENT))
        ).json()
        if item["id"] == created["id"]
    ]
    params = {key: mine[key] for key in ("subject_id", "service_type_id") if mine[key]}
    search = await client.get(
        "/api/v1/search",
        params={**params, "exclude_self": "true"},
        headers=auth_header(STUDENT),
    )
    assert search.status_code == 200, search.text
    return mine["helpers_seeing"], search.json()["total"]


async def test_an_open_request_counts_whom_the_catalog_lists_for_it(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    created = await post_request(client, "нужна помощь с матаном")
    assert created["subject_id"] is not None
    before, _ = await _seeing_and_listed(client, created)

    await helper_factory(tg_id=HELPER)
    # The same kind of help on another subject, and a draft: neither is listed.
    await helper_factory(tg_id=OTHER, subject_slug="akademicke-psani")
    draft = await helper_factory(tg_id=90504)
    profile = await session.get(HelperProfile, draft.id)
    assert profile is not None
    profile.status = PublishStatus.DRAFT
    await session.commit()

    seeing, listed = await _seeing_and_listed(client, created)
    assert seeing == before + 1
    assert seeing == listed

    closed = await client.post(
        f"/api/v1/requests/{created['id']}/close", headers=auth_header(STUDENT)
    )
    assert closed.json()["helpers_seeing"] == 0


async def test_the_author_is_not_among_the_helpers_seeing(
    client: AsyncClient, helper_factory
) -> None:
    """Nor among those the catalog offers to call instead of waiting."""
    await helper_factory(tg_id=STUDENT)
    created = await post_request(client, "нужна помощь с матаном")
    await post_request(client, "нужна помощь с матаном", tg_id=OTHER)
    [theirs] = (await client.get("/api/v1/requests", headers=auth_header(OTHER))).json()

    seeing, listed = await _seeing_and_listed(client, created)
    # The same subject: the one helper counted for the other request and not
    # for this one is the student themselves.
    assert created["subject_id"] == theirs["subject_id"]
    assert seeing == theirs["helpers_seeing"] - 1
    assert seeing == listed


# ── pricing an answer ───────────────────────────────────────────────────


async def test_the_feed_suggests_the_helpers_own_price(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER, price=650)
    created = await post_request(client, "нужна помощь с матаном")

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [item] = [item for item in feed if item["id"] == created["id"]]
    assert item["suggested_price"] == {"amount": 650, "currency": "CZK", "unit": "hour"}


async def test_no_price_is_suggested_far_from_the_helpers_offers(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER, price=650)
    created = await post_request(client, "кто-нибудь знает, где купить велосипед")

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [item] = [item for item in feed if item["id"] == created["id"]]
    assert item["suggested_price"] is None


async def test_an_offer_without_a_price_suggests_none(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER, price=None)
    created = await post_request(client, "нужна помощь с матаном")

    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [item] = [item for item in feed if item["id"] == created["id"]]
    assert item["suggested_price"] is None


async def _ids(session: AsyncSession, *, subject: str, service: str) -> tuple[int, int]:
    from students_cz.db.models import ServiceType, Subject

    subject_id = await session.scalar(select(Subject.id).where(Subject.slug == subject))
    service_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == service)
    )
    assert subject_id is not None and service_id is not None
    return subject_id, service_id


async def _asking(
    client: AsyncClient,
    session: AsyncSession,
    *,
    subject_id: int | None,
    service_type_id: int | None,
) -> int:
    """A request on exactly these axes, whatever the parser made of its text."""
    created = await post_request(client, "нужна помощь")
    request = await session.get(HelpRequest, created["id"])
    assert request is not None
    request.subject_id = subject_id
    request.service_type_id = service_type_id
    await session.commit()
    return created["id"]


async def _suggested(client: AsyncClient, request_id: int) -> dict | None:
    feed = (await client.get("/api/v1/requests/feed", headers=helper_header())).json()
    [item] = [item for item in feed if item["id"] == request_id]
    return item["suggested_price"]


async def test_the_price_comes_from_an_offer_fitting_every_axis_named(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """Not the hourly lesson rate for a coursework, nor calculus for law."""
    from students_cz.db.models import Offer
    from students_cz.db.models.enums import PriceUnit

    helper = await helper_factory(tg_id=HELPER, price=650)
    calculus, tutoring = await _ids(
        session, subject="matematicka-analyza", service="tutoring"
    )
    micro, writing = await _ids(session, subject="mikroekonomie", service="writing")
    law, _ = await _ids(session, subject="pravo", service="tutoring")
    session.add(
        Offer(
            helper_id=helper.id,
            service_type_id=writing,
            subject_id=micro,
            price_amount=2000,
            price_unit=PriceUnit.WORK,
            langs=["ru"],
        )
    )
    # Somebody else's offer, and a paused one of theirs: neither is theirs to quote.
    other = await helper_factory(tg_id=OTHER, price=100, subject_slug="pravo")
    session.add(
        Offer(
            helper_id=helper.id,
            service_type_id=tutoring,
            subject_id=law,
            price_amount=50,
            langs=["ru"],
            is_active=False,
        )
    )
    await session.commit()
    assert other.id != helper.id

    coursework = await _asking(
        client, session, subject_id=calculus, service_type_id=writing
    )
    on_law = await _asking(client, session, subject_id=law, service_type_id=tutoring)
    on_micro = await _asking(client, session, subject_id=micro, service_type_id=writing)
    lesson = await _asking(client, session, subject_id=calculus, service_type_id=tutoring)

    assert await _suggested(client, coursework) is None
    assert await _suggested(client, on_law) is None
    assert await _suggested(client, on_micro) == {
        "amount": 2000,
        "currency": "CZK",
        "unit": "work",
    }
    assert (await _suggested(client, lesson) or {}).get("amount") == 650


async def test_a_request_on_a_shelf_is_priced_from_what_it_holds(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    from students_cz.db.models import Subject

    await helper_factory(tg_id=HELPER, price=650)
    maths = await session.scalar(select(Subject.id).where(Subject.slug == "math"))
    assert maths is not None

    request_id = await _asking(client, session, subject_id=maths, service_type_id=None)
    assert (await _suggested(client, request_id) or {}).get("amount") == 650


async def test_several_fitting_offers_give_the_lowest_or_nothing(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    """The lowest within one unit; across units there is no honest guess."""
    from students_cz.db.models import Offer, Subject
    from students_cz.db.models.enums import PriceUnit

    helper = await helper_factory(tg_id=HELPER, price=650)
    maths = await session.scalar(select(Subject.id).where(Subject.slug == "math"))
    probability, exam_prep = await _ids(
        session, subject="pravdepodobnost-a-statistika", service="exam_prep"
    )
    _, tutoring = await _ids(session, subject="matematicka-analyza", service="tutoring")
    session.add(
        Offer(
            helper_id=helper.id,
            service_type_id=tutoring,
            subject_id=probability,
            price_amount=500,
            langs=["ru"],
        )
    )
    await session.commit()

    tutored = await _asking(client, session, subject_id=maths, service_type_id=tutoring)
    assert (await _suggested(client, tutored) or {}).get("amount") == 500

    session.add(
        Offer(
            helper_id=helper.id,
            service_type_id=exam_prep,
            subject_id=probability,
            price_amount=3000,
            price_unit=PriceUnit.SEMESTER,
            langs=["ru"],
        )
    )
    await session.commit()
    anything = await _asking(client, session, subject_id=maths, service_type_id=None)
    assert await _suggested(client, anything) is None


# ── the chips over the feed ─────────────────────────────────────────────


async def _feed(client: AsyncClient, **params) -> list[dict]:
    response = await client.get(
        "/api/v1/requests/feed",
        params={"limit": 50, **params},
        headers=helper_header(),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _facets(client: AsyncClient) -> dict:
    response = await client.get("/api/v1/requests/feed/facets", headers=helper_header())
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_feed_says_which_requests_are_on_the_helpers_services(
    client: AsyncClient, helper_factory
) -> None:
    await helper_factory(tg_id=HELPER)
    theirs = await post_request(client, "нужна помощь с матаном")
    other = await post_request(client, "помогите с нострификацией аттестата")

    by_id = {item["id"]: item for item in await _feed(client)}
    assert by_id[theirs["id"]]["on_my_services"] is True
    assert by_id[other["id"]]["on_my_services"] is False

    mine = [item["id"] for item in await _feed(client, mine="true")]
    assert theirs["id"] in mine
    assert other["id"] not in mine


async def test_a_shelf_chip_takes_in_what_the_shelf_holds(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    from students_cz.db.models import Subject

    await helper_factory(tg_id=HELPER)
    maths = await session.scalar(select(Subject.id).where(Subject.slug == "math"))
    before = {f["id"]: f["count"] for f in (await _facets(client))["subjects"]}

    calculus = await post_request(client, "нужна помощь с матаном")
    other = await post_request(client, "помогите с нострификацией аттестата")

    on_maths = [item["id"] for item in await _feed(client, subject_id=maths)]
    assert calculus["id"] in on_maths
    assert other["id"] not in on_maths
    after = {f["id"]: f["count"] for f in (await _facets(client))["subjects"]}
    assert after[maths] == before.get(maths, 0) + 1


async def test_format_city_and_budget_narrow_the_feed_and_are_counted(
    client: AsyncClient, session: AsyncSession, helper_factory
) -> None:
    from students_cz.db.models.enums import WorkFormat

    await helper_factory(tg_id=HELPER)
    before = await _facets(client)
    created = await post_request(client, "нужна помощь с матаном")
    request = await session.get(HelpRequest, created["id"])
    assert request is not None
    request.work_format = WorkFormat.OFFLINE
    request.city = "Testov"
    request.budget_max = 400
    # The same city spelled differently: one chip, as one filter matches both.
    twin = await post_request(client, "помогите с нострификацией аттестата")
    twin_request = await session.get(HelpRequest, twin["id"])
    assert twin_request is not None
    twin_request.city = "testov"
    twin_request.work_format = WorkFormat.ONLINE
    await session.commit()

    def shown(items: list[dict]) -> bool:
        return created["id"] in [item["id"] for item in items]

    assert shown(await _feed(client, work_format="offline"))
    assert not shown(await _feed(client, work_format="online"))
    assert shown(await _feed(client, city="testov"))
    assert not shown(await _feed(client, city="Brno"))
    assert shown(await _feed(client, budget_upto=500))
    assert not shown(await _feed(client, budget_upto=300))

    after = await _facets(client)
    assert after["all"] == before["all"] + 2
    assert after["formats"]["offline"] == before["formats"]["offline"] + 1
    assert {"name": "Testov", "count": 2} in after["cities"]
    assert not [c for c in after["cities"] if c["name"] == "testov"]
    steps = {b["amount"]: b["count"] for b in after["budget_upto"]}
    old = {b["amount"]: b["count"] for b in before["budget_upto"]}
    assert steps[500] == old[500] + 1
