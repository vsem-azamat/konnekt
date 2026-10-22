"""The catalog in reverse: a student posts, helpers answer.

Everything a request goes through — posted, listed, answered, read, accepted,
declined, closed — plus the feed that decides which open requests a helper is
shown and in what order. The feed is the second-largest algorithm in the
product; the rest is a state machine with an audience on both sides.

All of it is rules about the catalog rather than facts about HTTP, so the
endpoints above this only parse, delegate, render, and send the notifications
that each step owes somebody.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import ColumnElement, and_, false, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    Contact,
    HelperProfile,
    HelpRequest,
    Institution,
    Offer,
    RequestResponse,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import (
    ContentLang,
    NodeKind,
    PriceUnit,
    PublishStatus,
    RequestStatus,
    ResponseStatus,
    UiLang,
    UserEventKind,
    WorkFormat,
)
from students_cz.services import catalog, parser
from students_cz.services.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
)
from students_cz.services.lookup import held_by, shelves_by_subject, shelves_of
from students_cz.services.people import log_event
from students_cz.services.refs import require_row


@dataclass(frozen=True, slots=True)
class FeedRow:
    """One request, its author, and which of the helper's axes it hit.

    The three flags are the contract, not the sentence built out of them: the
    line the reader sees is rendered from these, and it has to name the same
    axis that lifted the row or it reads as a non sequitur.
    """

    request: HelpRequest
    author: User
    on_subject: bool
    on_institution: bool
    on_service: bool
    responded: bool = False
    # «По твоим услугам»: one of the helper's offers fits it — see `_fits_an_offer`.
    on_my_services: bool = False


@dataclass(frozen=True, slots=True)
class FeedFilters:
    """The chips over the feed, every one of them narrowing it further."""

    mine: bool = False
    # Those the helper already answered. Off unless asked for: a client that
    # does not mark them offers to answer again and gets a 409.
    with_responded: bool = False
    service_type_id: int | None = None
    # A shelf takes in what it holds, as in the catalog's search.
    subject_id: int | None = None
    work_format: WorkFormat | None = None
    city: str | None = None
    budget_upto: float | None = None


@dataclass(frozen=True, slots=True)
class Facet:
    id: int
    count: int


@dataclass(frozen=True, slots=True)
class FeedFacets:
    """What each chip over the feed would leave, counted over the whole feed."""

    all: int
    mine: int
    subjects: list[Facet]
    service_types: list[Facet]
    online: int
    offline: int
    cities: list[tuple[str, int]]
    budget_upto: list[tuple[int, int]]


# The budget chips: «До 500 Kč», «До 1000 Kč».
BUDGET_STEPS = (500, 1000)


def live(now: datetime) -> ColumnElement[bool]:
    """A request somebody can still answer: open, and not past its deadline.

    Expiry is a deadline and not a job that has to have run, so `status`
    alone still reads `open` on a request that already refuses answers.
    """
    return and_(
        HelpRequest.status == RequestStatus.OPEN,
        or_(HelpRequest.expires_at.is_(None), HelpRequest.expires_at > now),
    )


async def _may_read_feed(session: AsyncSession, user: User) -> None:
    """Any helper profile including a draft one, and no banned one.

    Seeing that four people want help with the thing you teach is the argument
    for finishing the profile, and withholding it until published gets that
    backwards. What a draft cannot do is answer.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None:
        raise Forbidden("only helpers can see incoming requests")
    # A ban has to cover this too. The feed carries every author's name, photo,
    # full text and budget — for someone banned for harassment it is a target
    # list, and being unable to answer in-app does not help if the reason they
    # were banned is that they contact people outside it.
    if helper.status is PublishStatus.BANNED:
        raise Forbidden("this profile is banned")


async def feed_for(
    session: AsyncSession,
    *,
    user: User,
    limit: int,
    filters: FeedFilters | None = None,
) -> list[FeedRow]:
    """Open requests, for someone who could answer them, best fit first.

    Those already answered are left out unless asked for, and then come
    after every unanswered one, marked: «Отклик отправлен» is what the helper
    looks for after answering, but it must not push a new request off the page.
    """
    await _may_read_feed(session, user)

    subject_ids, institution_ids, service_ids = await _axes_of(session, user)

    subject_match = _matches(HelpRequest.subject_id, subject_ids)
    institution_match = _matches(HelpRequest.institution_id, institution_ids)
    service_match = _matches(HelpRequest.service_type_id, service_ids)

    # Strongest signal first. Anything the helper has no axis for is dropped
    # rather than ordered by, since it would sort every row identically.
    ranking = [
        term.desc()
        for term in (subject_match, service_match, institution_match)
        if term is not None
    ]

    now = datetime.now(UTC)
    answered = _answered_by(user)

    filters = filters or FeedFilters()
    narrowing = await _narrowing(session, filters)
    fits = await _fits_an_offer(session, user)
    if fits is not None:
        # A request one offer fits outranks one that only shares an axis
        # with some offer: calculus coursework is not a calculus tutor's.
        ranking.insert(0, fits.desc())
    if filters.mine:
        narrowing.append(fits if fits is not None else false())
    if filters.with_responded:
        # False sorts first: the unanswered, then the answered.
        ranking.insert(0, answered.asc())
    else:
        narrowing.append(~answered)

    rows = (
        await session.execute(
            select(
                HelpRequest,
                User,
                subject_match if subject_match is not None else false(),
                institution_match if institution_match is not None else false(),
                service_match if service_match is not None else false(),
                answered,
                fits if fits is not None else false(),
            )
            .join(User, User.id == HelpRequest.author_id)
            .where(
                live(now),
                # Answering your own request is not a thing.
                HelpRequest.author_id != user.id,
                *narrowing,
            )
            .order_by(
                *ranking,
                HelpRequest.created_at.desc(),
                # Total, so paging is stable: created_at is the transaction
                # clock and rows written together share it.
                HelpRequest.id.desc(),
            )
            .limit(limit)
        )
    ).all()

    return [
        FeedRow(
            request=request,
            author=author,
            on_subject=bool(on_subject),
            on_institution=bool(on_institution),
            on_service=bool(on_service),
            responded=bool(responded),
            on_my_services=bool(mine),
        )
        for request, author, on_subject, on_institution, on_service, responded, mine in (
            rows
        )
    ]


async def suggested_offers(
    session: AsyncSession, *, user: User, requests: list[HelpRequest]
) -> dict[int, Offer]:
    """The helper's own offer to price an answer to each request from.

    One that fits every axis the request names, as the catalog's search
    would: the kind of help, and a subject on or under the one it names. A
    calculus tutor answering «матан» quotes their calculus price; a coursework
    request does not get an hourly lesson rate. Several fitting offers in one
    unit give the lowest; in different units nothing is said rather than a
    guess. A request naming neither axis, or an offer with no price, gives
    nothing.
    """
    offers = list(
        await session.scalars(
            select(Offer)
            .where(
                Offer.helper_id == user.id,
                Offer.is_active.is_(True),
                Offer.price_amount.is_not(None),
            )
            .order_by(Offer.id)
        )
    )
    if not offers:
        return {}
    # Per offer and not per request: a helper has a handful of offers, a page
    # has fifty requests. `shelves_of` is `held_by` read the other way.
    shelves = await shelves_by_subject(
        session, {o.subject_id for o in offers if o.subject_id is not None}
    )
    suggested: dict[int, Offer] = {}
    for request in requests:
        if request.subject_id is None and request.service_type_id is None:
            continue
        fitting = [
            offer
            for offer in offers
            if (
                request.service_type_id is None
                or offer.service_type_id == request.service_type_id
            )
            and (
                request.subject_id is None
                or request.subject_id in shelves.get(offer.subject_id, set())
            )
        ]
        if fitting and len({offer.price_unit for offer in fitting}) == 1:
            suggested[request.id] = min(fitting, key=lambda o: (o.price_amount, o.id))
    return suggested


def _answered_by(user: User):
    return (
        select(RequestResponse.id)
        .where(
            RequestResponse.request_id == HelpRequest.id,
            RequestResponse.helper_id == user.id,
        )
        .exists()
    )


async def _fits_an_offer(session: AsyncSession, user: User) -> ColumnElement[bool] | None:
    """One of the helper's offers fits every axis the request names.

    The rule `suggested_offers` prices by: a calculus tutor's offer fits a
    calculus or maths request, not every tutoring request on any subject. A
    request naming neither axis fits nothing. None when the helper has no
    active offer.
    """
    offers = set(
        (
            await session.execute(
                select(Offer.subject_id, Offer.service_type_id).where(
                    Offer.helper_id == user.id, Offer.is_active.is_(True)
                )
            )
        ).tuples()
    )
    if not offers:
        return None
    shelves = await shelves_by_subject(
        session, {subject_id for subject_id, _ in offers if subject_id is not None}
    )
    no_subject = HelpRequest.subject_id.is_(None)
    no_service = HelpRequest.service_type_id.is_(None)
    each = [
        and_(
            no_subject
            if subject_id is None
            else or_(no_subject, HelpRequest.subject_id.in_(shelves[subject_id])),
            no_service
            if service_type_id is None
            else or_(no_service, HelpRequest.service_type_id == service_type_id),
        )
        for subject_id, service_type_id in sorted(offers, key=str)
    ]
    return and_(~and_(no_subject, no_service), or_(*each))


async def _narrowing(session: AsyncSession, filters: FeedFilters) -> list:
    where: list = []
    if filters.service_type_id is not None:
        where.append(HelpRequest.service_type_id == filters.service_type_id)
    if filters.subject_id is not None:
        where.append(
            HelpRequest.subject_id.in_(await held_by(session, filters.subject_id))
        )
    if filters.work_format is not None and filters.work_format is not WorkFormat.BOTH:
        where.append(HelpRequest.work_format.in_((filters.work_format, WorkFormat.BOTH)))
    if filters.city is not None:
        where.append(func.lower(HelpRequest.city) == filters.city.lower())
    if filters.budget_upto is not None:
        where.append(HelpRequest.budget_max <= filters.budget_upto)
    return where


async def feed_facets(
    session: AsyncSession, *, user: User, with_responded: bool = False
) -> FeedFacets:
    """Counts for the chips, each over the whole feed and not the chosen one.

    Over the same requests the feed shows: without those already answered
    unless asked for, so `mine` is what is still waiting for this helper.

    The feed is every open request of others, a few hundred at most, so it is
    read once and counted here rather than once per chip in SQL.
    """
    await _may_read_feed(session, user)
    fits = await _fits_an_offer(session, user)
    where = [live(datetime.now(UTC)), HelpRequest.author_id != user.id]
    if not with_responded:
        where.append(~_answered_by(user))
    rows = (
        await session.execute(
            select(
                HelpRequest.subject_id,
                HelpRequest.service_type_id,
                HelpRequest.work_format,
                HelpRequest.city,
                HelpRequest.budget_max,
                (fits if fits is not None else false()).label("fits"),
            ).where(*where)
        )
    ).all()

    # Chips name shelves: «Математика» over calculus and linear algebra both,
    # and a request on a leaf two shelves hold counts under each.
    shelves = await shelves_by_subject(
        session, {row.subject_id for row in rows if row.subject_id is not None}
    )
    groups = set(
        await session.scalars(
            select(Subject.id).where(
                Subject.id.in_(set().union(*shelves.values()) or {0}),
                Subject.kind == NodeKind.GROUP,
            )
        )
    )

    by_shelf: dict[int, int] = {}
    by_service: dict[int, int] = {}
    by_city: dict[str, int] = {}
    # Cities group case-insensitively, as the filter matches them; the chip
    # shows the first spelling seen.
    city_label: dict[str, str] = {}
    mine = online = offline = 0
    for row in rows:
        if row.fits:
            mine += 1
        for shelf in shelves.get(row.subject_id, set()) & groups:
            by_shelf[shelf] = by_shelf.get(shelf, 0) + 1
        if row.service_type_id is not None:
            by_service[row.service_type_id] = by_service.get(row.service_type_id, 0) + 1
        if row.work_format in (WorkFormat.ONLINE, WorkFormat.BOTH):
            online += 1
        if row.work_format in (WorkFormat.OFFLINE, WorkFormat.BOTH):
            offline += 1
        if row.city:
            key = row.city.lower()
            city_label.setdefault(key, row.city)
            by_city[key] = by_city.get(key, 0) + 1

    def ranked(counts: dict) -> list:
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return FeedFacets(
        all=len(rows),
        mine=mine,
        subjects=[Facet(id=id_, count=count) for id_, count in ranked(by_shelf)],
        service_types=[Facet(id=id_, count=count) for id_, count in ranked(by_service)],
        online=online,
        offline=offline,
        cities=[(city_label[key], count) for key, count in ranked(by_city)],
        budget_upto=[
            (
                step,
                sum(
                    1
                    for row in rows
                    if row.budget_max is not None and row.budget_max <= step
                ),
            )
            for step in BUDGET_STEPS
        ],
    )


async def _axes_of(
    session: AsyncSession, user: User
) -> tuple[set[int], set[int], set[int]]:
    """What this helper actually offers, as three sets of ids."""
    axes = (
        await session.execute(
            select(Offer.subject_id, Offer.institution_id, Offer.service_type_id).where(
                Offer.helper_id == user.id, Offer.is_active.is_(True)
            )
        )
    ).all()
    subject_ids = {row[0] for row in axes if row[0]}
    # And every shelf that holds them: a request for «математика» is a request
    # on the subject of somebody teaching linear algebra, or maths for
    # economists. Upwards only — calculus is maths, maths is not calculus.
    subject_ids = await shelves_of(session, subject_ids)
    institution_ids = {row[1] for row in axes if row[1]}
    service_ids = {row[2] for row in axes if row[2]}
    # Their own faculty counts too — a request from your own school is
    # relevant whether or not you have listed an offer against it.
    if user.institution_id:
        institution_ids.add(user.institution_id)
    return subject_ids, institution_ids, service_ids


def _matches(column, ids: set[int]):
    """Does this request hit one of the helper's axes?

    coalesce, because `subject_id IN (...)` is NULL for a request with no
    subject, and NULL sorts *first* under DESC — which would rank every vague
    request above every matching one.

    None when the helper has nothing on that axis: the term is then a
    constant, and a constant cannot go in ORDER BY — Postgres reads a bare
    `false` there as a column ordinal and rejects it.
    """
    if not ids:
        return None
    return func.coalesce(column.in_(ids), False)


async def create(
    session: AsyncSession,
    *,
    user: User,
    text: str,
    lang: UiLang,
    subject_id: int | None = None,
    institution_id: int | None = None,
    service_type_id: int | None = None,
    deadline_on: date | None = None,
    budget_max: float | None = None,
    langs: list[str] | None = None,
    work_format: WorkFormat | None = None,
    city: str | None = None,
    given: frozenset[str],
) -> HelpRequest:
    """Post "I need help with X" and let helpers answer.

    Anything the caller did not fill in is read out of the text, so the form
    can be a single field. A request without a deadline expires in thirty
    days; with one, the day after — an exam on the 14th is worthless on the
    15th, and a stale board is worse than an empty one.

    `given` is the set of field names the caller actually mentioned, and it is
    what separates "did not say" from "said none" — the same rule
    `HelperUpsert` follows through `model_fields_set`. The screen that posts a
    request shows the parse back as chips, so removing one sends `null` on
    purpose; without this the text would put it straight back.

    The format and the city are never read from the text: either is whatever
    was sent, and help given online is in no city.

    It has no default on purpose: it decides whether the five axis arguments
    above mean anything at all, so a caller that forgot it would watch every one
    of them be quietly replaced by whatever the parser made of the text.
    """
    await require_row(session, Subject, subject_id, "subject_id")
    await require_row(session, Institution, institution_id, "institution_id")
    await require_row(session, ServiceType, service_type_id, "service_type_id")

    parsed = await parser.parse(session, text, lang.value)

    if "subject_id" not in given:
        subject_id = parsed.subject.id if parsed.subject else None
    if "institution_id" not in given:
        institution_id = parsed.institution.id if parsed.institution else None
    if "service_type_id" not in given and parsed.service_type:
        service_type_id = await session.scalar(
            select(ServiceType.id).where(ServiceType.code == parsed.service_type)
        )
    deadline = deadline_on if "deadline_on" in given else parsed.deadline
    if "budget_max" not in given:
        budget_max = parsed.budget_max
    work_format = work_format or WorkFormat.BOTH
    city = (city or None) if work_format is not WorkFormat.ONLINE else None

    # A double tap, or a reload, rather than a second thing to answer. Same
    # author, same subject, same kind of help, same deadline, still open.
    #
    # Every axis is in the key, and the last clause has to exist:
    # half the catalog is help with no subject at all — insurance, a bank
    # statement, housing — so a rule keyed on the subject alone reads two NULLs
    # as a match and answers 409 to somebody who asked about a visa yesterday
    # and about a flat today. When none of the three axes is known there is
    # nothing to compare but the words, and identical words are the double tap
    # this is here for.
    # A date is not an identity. Two people's errands land on the same exam
    # week all the time, so a deadline alone must not switch the words off —
    # otherwise «закрыть долг к 14 февраля» refuses «перевести документы к
    # 14 февраля», which share nothing but the date.
    known = (
        subject_id is not None
        or service_type_id is not None
        or institution_id is not None
    )
    now = datetime.now(UTC)
    duplicate = await session.scalar(
        select(HelpRequest.id).where(
            HelpRequest.author_id == user.id,
            # Not just `open`: without the deadline the person is refused a
            # second ask by a request that already refuses answers.
            live(now),
            HelpRequest.subject_id.is_not_distinct_from(subject_id),
            HelpRequest.service_type_id.is_not_distinct_from(service_type_id),
            # The school belongs in the key for the same reason the sheet lets
            # you take it off: calculus at ČVUT and calculus at VŠE are two
            # different asks, and the row stores which.
            HelpRequest.institution_id.is_not_distinct_from(institution_id),
            HelpRequest.deadline_on.is_not_distinct_from(deadline),
            # Moving house in Brno and in Praha are two asks; a retry sends
            # the same payload, so these cost nothing in catching it.
            HelpRequest.work_format == work_format,
            HelpRequest.city.is_not_distinct_from(city),
            true() if known else HelpRequest.raw_text == text,
        )
    )
    if duplicate is not None:
        raise Conflict("you already have an open request for this")

    request = HelpRequest(
        author_id=user.id,
        raw_text=text,
        lang=ContentLang(lang.value),
        subject_id=subject_id,
        institution_id=institution_id,
        service_type_id=service_type_id,
        deadline_on=deadline,
        budget_max=budget_max,
        langs=langs or list(user.spoken_langs),
        work_format=work_format,
        city=city,
        status=RequestStatus.OPEN,
        expires_at=(
            datetime.combine(deadline, time.max, tzinfo=UTC)
            if deadline
            else datetime.now(UTC) + timedelta(days=30)
        ),
    )
    session.add(request)
    await log_event(
        session,
        user.id,
        UserEventKind.REQUEST_CREATED,
        subject_id=subject_id,
        institution_id=institution_id,
    )
    # flush, not commit: the row has to exist for `refresh` to read the
    # defaults the database fills in, but the transaction belongs to the
    # request and ends when the request does.
    await session.flush()
    await session.refresh(request)
    return request


# Nobody is reading their five-hundredth request, and an unbounded list is a
# query that gets slower for exactly the people who use the product most.
MY_REQUESTS_LIMIT = 50


async def mine(session: AsyncSession, *, user: User) -> list[HelpRequest]:
    """Your own, newest first."""
    return list(
        (
            await session.scalars(
                select(HelpRequest)
                .where(HelpRequest.author_id == user.id)
                # id as a tiebreaker: created_at comes from now(), which is the
                # transaction's clock, so two rows written together share it.
                .order_by(HelpRequest.created_at.desc(), HelpRequest.id.desc())
                .limit(MY_REQUESTS_LIMIT)
            )
        ).all()
    )


# ── the lifecycle ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Answered:
    """A new answer, and who has to be told about it."""

    response: RequestResponse
    request: HelpRequest
    author: User | None


@dataclass(frozen=True, slots=True)
class Accepted:
    """An acceptance, and whether it is the one that changed anything.

    `notify` is false on a repeat. Accepting is idempotent, so the second tap
    must not send the helper a second "you were picked".
    """

    response: RequestResponse
    request: HelpRequest
    helper: User | None
    notify: bool


async def respond(
    session: AsyncSession,
    *,
    user: User,
    request_id: int,
    message: str,
    price_amount: float | None = None,
    price_unit: PriceUnit | None = None,
) -> Answered:
    """Answer someone's request.

    Published profiles only, unlike the feed: an answer is an invitation to
    look at a profile, and a draft is not there to be looked at.
    """
    helper = await session.get(HelperProfile, user.id)
    if helper is None or helper.status is not PublishStatus.PUBLISHED:
        raise Forbidden("publish your profile before answering requests")
    # The same rule contacting a helper enforces, for the same reason: we do
    # not host the conversation, so a public username is the only way the
    # author can answer back. Without it an accepted answer is a dead end —
    # both sides told a deal happened and neither able to reach the other.
    if not user.tg_username:
        raise Conflict("set a public @username in Telegram so people can write back")

    request = await session.get(HelpRequest, request_id)
    if request is None:
        raise NotFound("no such request")
    if request.author_id == user.id:
        raise BadRequest("this is your own request")
    expired = request.expires_at is not None and request.expires_at <= datetime.now(UTC)
    if request.status is not RequestStatus.OPEN or expired:
        raise Conflict("this request is closed")

    # ON CONFLICT rather than a select first: two taps on a slow connection
    # are two concurrent inserts, and the unique constraint would surface the
    # second as a 500 instead of "you already answered this".
    inserted = await session.scalar(
        pg_insert(RequestResponse)
        .values(
            request_id=request.id,
            helper_id=user.id,
            message=message.strip(),
            price_amount=price_amount,
            price_unit=price_unit,
        )
        .on_conflict_do_nothing(constraint="uq_request_responses_pair")
        .returning(RequestResponse)
    )
    if inserted is None:
        raise Conflict("you have already answered this request")

    await log_event(
        session,
        user.id,
        UserEventKind.REQUEST_RESPONDED,
        request_id=request.id,
        subject_id=request.subject_id,
    )
    return Answered(
        response=inserted,
        request=request,
        author=await session.get(User, request.author_id),
    )


async def responses_for_author(
    session: AsyncSession, *, user: User, request_id: int
) -> list[RequestResponse]:
    """Who answered. The author only — this is not a public bid list."""
    request = await session.get(HelpRequest, request_id)
    if request is None or request.author_id != user.id:
        raise NotFound("no such request")

    return list(
        (
            await session.scalars(
                select(RequestResponse)
                .where(RequestResponse.request_id == request.id)
                .order_by(RequestResponse.created_at.asc(), RequestResponse.id.asc())
            )
        ).all()
    )


def mark_read(responses: list[RequestResponse]) -> None:
    """Separate from reading them, because the order matters.

    The caller renders first: marking before the answer goes out means the
    author receives them already read and never gets to badge the new ones.
    Only the ones still unread change, so an accepted or declined answer is
    not quietly walked backwards.
    """
    for response in responses:
        if response.status is ResponseStatus.SENT:
            response.status = ResponseStatus.READ


async def accept(session: AsyncSession, *, user: User, response_id: int) -> Accepted:
    """Pick someone.

    Does not close the request: needing two people for two subjects is
    ordinary, and closing on the first acceptance would make the common case
    the destructive one.
    """
    response, request = await _own_response(session, response_id, user)

    # Idempotent. A double tap, or a retry after a dropped response, would
    # otherwise write a second `contacts` row — which is the basis for deal
    # counts and response times — and send the helper a second "you were
    # picked". `contacts` has no unique index to catch it, and should not:
    # contacting the same person twice about two different requests is real.
    if response.status is ResponseStatus.ACCEPTED:
        return Accepted(response=response, request=request, helper=None, notify=False)

    response.status = ResponseStatus.ACCEPTED

    # The same row the catalog writes when someone taps "write" on a profile,
    # so response times and deal counts count both routes to a conversation.
    session.add(
        Contact(
            student_id=user.id,
            helper_id=response.helper_id,
            request_id=request.id,
        )
    )
    await log_event(
        session,
        user.id,
        UserEventKind.RESPONSE_ACCEPTED,
        request_id=request.id,
        helper_id=response.helper_id,
    )
    return Accepted(
        response=response,
        request=request,
        helper=await session.get(User, response.helper_id),
        notify=True,
    )


async def decline(
    session: AsyncSession, *, user: User, response_id: int
) -> RequestResponse:
    """Turn one down. Deliberately silent — nobody needs a rejection push."""
    response, _ = await _own_response(session, response_id, user)

    # An accepted answer cannot be walked back. The helper has already been
    # told they were picked and a `contacts` row exists; flipping the status
    # would leave the author reading "you declined" while the other side reads
    # "you were chosen", with a recorded deal between them.
    if response.status is ResponseStatus.ACCEPTED:
        raise Conflict("you already chose this person")

    response.status = ResponseStatus.DECLINED
    return response


async def close(session: AsyncSession, *, user: User, request_id: int) -> HelpRequest:
    """Stop taking answers."""
    request = await _own_request(session, user=user, request_id=request_id)
    if request.status is not RequestStatus.CLOSED:
        request.status = RequestStatus.CLOSED
        request.closed_at = datetime.now(UTC)
    return request


async def delete(session: AsyncSession, *, user: User, request_id: int) -> None:
    """Remove a request and every answer to it, for good."""
    await session.delete(await _own_request(session, user=user, request_id=request_id))


async def _own_request(
    session: AsyncSession, *, user: User, request_id: int
) -> HelpRequest:
    """404 for someone else's as for a missing one, as with responses below."""
    request = await session.get(HelpRequest, request_id)
    if request is None or request.author_id != user.id:
        raise NotFound("no such request")
    return request


async def helpers_seeing(
    session: AsyncSession, requests: list[HelpRequest]
) -> dict[int, int]:
    """How many people the catalog lists for each request, its author aside.

    Exactly the `/search` on the request's subject and kind of help that the
    screen offers beneath the number, so the two never disagree. A request
    naming neither has nobody to count.
    """
    counts: dict[int, int] = {}
    for request in requests:
        if request.subject_id is None and request.service_type_id is None:
            counts[request.id] = 0
            continue
        counts[request.id] = await catalog.count_helpers(
            session,
            subject_id=request.subject_id,
            service_type_id=request.service_type_id,
            exclude_helper_id=request.author_id,
        )
    return counts


async def _own_response(
    session: AsyncSession, response_id: int, user: User
) -> tuple[RequestResponse, HelpRequest]:
    """Load a response the caller is entitled to act on.

    404 rather than 403 for someone else's: whether a given id exists is not
    something a stranger should be able to probe.
    """
    response = await session.get(RequestResponse, response_id)
    if response is None:
        raise NotFound("no such response")
    request = await session.get(HelpRequest, response.request_id)
    if request is None or request.author_id != user.id:
        raise NotFound("no such response")
    return response, request
