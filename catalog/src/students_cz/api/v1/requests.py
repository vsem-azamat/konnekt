"""The catalog in reverse: a student posts, helpers answer.

The largest domain here, because a request has a life — posted, seen, answered,
accepted, closed — and every step of it notifies somebody.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, status
from sqlalchemy import func, select

from students_cz.api.deps import (
    IdPath,
    IdQuery,
    LangDep,
    NotifierDep,
    SessionDep,
    UserDep,
)
from students_cz.bot.texts import (
    FOR_PRICE,
    NEW_RESPONSE,
    OWNER_NEW_REQUEST,
    OWNER_NOTHING_PARSED,
    RESPONSE_ACCEPTED,
    WAIT_FOR_MESSAGE,
    WRITE_TO,
    pick,
)
from students_cz.db.models import (
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
    PriceUnit,
    RequestStatus,
    WorkFormat,
)
from students_cz.schemas import (
    BudgetCount,
    CityCount,
    FacetOut,
    FeedFacetsOut,
    FeedRequestOut,
    FormatCounts,
    Phrase,
    Price,
    RequestCreate,
    RequestOut,
    ResponseCreate,
    ResponseOut,
)
from students_cz.services import requests as requests_service
from students_cz.services.catalog import avatar_for
from students_cz.services.naming import names_by_id, rows_by_id, short_form, translated
from students_cz.services.notify import Recipient, money, quote
from students_cz.services.people import full_name

router = APIRouter()


@router.post(
    "/requests",
    response_model=RequestOut,
    status_code=status.HTTP_201_CREATED,
    tags=["requests"],
)
async def create_request(
    payload: RequestCreate,
    background: BackgroundTasks,
    notifier: NotifierDep,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> RequestOut:
    """Post "I need help with X" and let helpers answer."""
    request = await requests_service.create(
        session,
        user=user,
        text=payload.text,
        lang=lang,
        subject_id=payload.subject_id,
        institution_id=payload.institution_id,
        service_type_id=payload.service_type_id,
        deadline_on=payload.deadline_on,
        budget_max=payload.budget_max,
        langs=payload.langs,
        work_format=payload.work_format,
        city=payload.city,
        # What the caller actually mentioned. A chip the person removed arrives
        # as an explicit `null`, which means "any" and not "work it out".
        given=frozenset(payload.model_fields_set),
    )
    rendered = await _request_out(session, request, lang)
    # The helpers who could answer hear about it later, from
    # services/request_alerts.py; the owner hears about every request now.
    background.add_task(
        notifier.tell_owner,
        OWNER_NEW_REQUEST.format(
            topic=quote(await _axes_line(session, request), 120),
            text=quote(request.raw_text),
        ),
    )
    return rendered


@router.get("/requests", response_model=list[RequestOut], tags=["requests"])
async def my_requests(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[RequestOut]:
    """Your own, newest first."""
    return await _requests_out(
        session, await requests_service.mine(session, user=user), lang
    )


@router.get("/requests/feed", response_model=list[FeedRequestOut], tags=["requests"])
async def request_feed(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    limit: int = Query(20, ge=1, le=50),
    mine: bool = False,
    with_responded: bool = False,
    service_type_id: IdQuery = None,
    subject_id: IdQuery = None,
    work_format: WorkFormat | None = None,
    city: Annotated[str | None, Query(max_length=96)] = None,
    budget_upto: Annotated[
        float | None, Query(ge=0, le=1_000_000, allow_inf_nan=False)
    ] = None,
) -> list[FeedRequestOut]:
    """Open requests, for someone who could answer them, narrowed by the chips."""
    rows = await requests_service.feed_for(
        session,
        user=user,
        limit=limit,
        filters=requests_service.FeedFilters(
            mine=mine,
            with_responded=with_responded,
            service_type_id=service_type_id,
            subject_id=subject_id,
            work_format=work_format,
            city=city or None,
            budget_upto=budget_upto,
        ),
    )

    rendered = await _requests_out(
        session, [row.request for row in rows], lang, count_seeing=False
    )
    subjects_by_id = {item.id: item.subject for item in rendered}
    offers = await requests_service.suggested_offers(
        session, user=user, requests=[row.request for row in rows]
    )

    return [
        FeedRequestOut(
            # Only the shared fields. `responses_count` and `responders` are
            # not on FeedRequestOut at all — see the schema.
            **base.model_dump(exclude={"responders", "responses_count"}),
            author=avatar_for(row.author),
            author_name=row.author.first_name,
            budget=(
                Price(
                    amount=float(row.request.budget_max),
                    currency=row.request.budget_currency,
                    unit=row.request.budget_unit or PriceUnit.HOUR,
                )
                if row.request.budget_max is not None
                else None
            ),
            langs=list(row.request.langs),
            reason=_feed_reason(
                on_subject=row.on_subject,
                on_institution=row.on_institution,
                on_service=row.on_service,
                subject=subjects_by_id.get(row.request.id),
            ),
            suggested_price=_offer_price(offers.get(row.request.id)),
            on_my_services=row.on_my_services,
            responded=row.responded,
        )
        for base, row in zip(rendered, rows, strict=True)
    ]


def _offer_price(offer: Offer | None) -> Price | None:
    if offer is None or offer.price_amount is None:
        return None
    return Price(
        amount=float(offer.price_amount),
        currency=offer.price_currency,
        unit=offer.price_unit,
    )


@router.get("/requests/feed/facets", response_model=FeedFacetsOut, tags=["requests"])
async def request_feed_facets(
    session: SessionDep, lang: LangDep, user: UserDep, with_responded: bool = False
) -> FeedFacetsOut:
    """The numbers on the chips over the feed, each over the whole feed."""
    facets = await requests_service.feed_facets(
        session, user=user, with_responded=with_responded
    )
    subject_names = await names_by_id(
        session, Subject, [facet.id for facet in facets.subjects], lang
    )
    service_names = await names_by_id(
        session, ServiceType, [facet.id for facet in facets.service_types], lang
    )
    return FeedFacetsOut(
        all=facets.all,
        mine=facets.mine,
        subjects=[
            FacetOut(id=f.id, name=subject_names.get(f.id, ""), count=f.count)
            for f in facets.subjects
        ],
        service_types=[
            FacetOut(id=f.id, name=service_names.get(f.id, ""), count=f.count)
            for f in facets.service_types
        ],
        formats=FormatCounts(online=facets.online, offline=facets.offline),
        cities=[CityCount(name=name, count=count) for name, count in facets.cities],
        budget_upto=[
            BudgetCount(amount=amount, count=count)
            for amount, count in facets.budget_upto
        ],
    )


def _feed_reason(
    *, on_subject: bool, on_institution: bool, on_service: bool, subject: str | None
) -> Phrase | None:
    """Why this request is in the list.

    One line, strongest first — and in the *same* order the ranking uses, or
    the line names a weaker axis than the one that actually lifted the row and
    reads as a non sequitur next to its neighbours.
    """
    if on_subject and subject:
        return Phrase(code="feed.same_subject", params={"subject": subject})
    if on_service:
        return Phrase(code="feed.same_service")
    if on_institution:
        return Phrase(code="feed.same_institution")
    return None


@router.post(
    "/requests/{request_id}/respond",
    response_model=ResponseOut,
    status_code=status.HTTP_201_CREATED,
    tags=["requests"],
)
async def respond_to_request(
    request_id: IdPath,
    payload: ResponseCreate,
    background: BackgroundTasks,
    notifier: NotifierDep,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> ResponseOut:
    """Answer someone's request."""
    answered = await requests_service.respond(
        session,
        user=user,
        request_id=request_id,
        message=payload.message,
        price_amount=payload.price_amount,
        price_unit=payload.price_unit,
    )

    [rendered] = await _responses_out(session, [answered.response], lang)
    author = answered.author
    if author is not None:
        # After the response goes out, not before: Telegram is a network call
        # to a third party in the middle of a request somebody is waiting on,
        # and the action is already committed.
        background.add_task(
            notifier.tell,
            Recipient.of(author),
            pick(NEW_RESPONSE, author.ui_lang).format(
                topic=quote(_topic_of(rendered_request=answered.request), 120),
                helper=quote(rendered.name, 64),
                price=(
                    pick(FOR_PRICE, author.ui_lang).format(
                        price=_price_line(rendered.price)
                    )
                    if rendered.price and rendered.price.amount is not None
                    else ""
                ),
                message=quote(answered.response.message),
            ),
        )
    return rendered


@router.get(
    "/requests/{request_id}/responses",
    response_model=list[ResponseOut],
    tags=["requests"],
)
async def request_responses(
    request_id: IdPath, session: SessionDep, lang: LangDep, user: UserDep
) -> list[ResponseOut]:
    """Who answered. The author only — this is not a public bid list."""
    rows = await requests_service.responses_for_author(
        session, user=user, request_id=request_id
    )

    # Rendered *before* marking anything, so this response still carries the
    # statuses the author has not seen yet — otherwise the client never gets a
    # chance to badge the new ones, because they arrive already read.
    out = await _responses_out(session, rows, lang)
    requests_service.mark_read(rows)
    return out


@router.post(
    "/responses/{response_id}/accept",
    response_model=ResponseOut,
    tags=["requests"],
)
async def accept_response(
    response_id: IdPath,
    background: BackgroundTasks,
    notifier: NotifierDep,
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
) -> ResponseOut:
    """Pick someone."""
    accepted = await requests_service.accept(session, user=user, response_id=response_id)

    helper_user = accepted.helper
    if accepted.notify and helper_user is not None:
        background.add_task(
            notifier.tell,
            Recipient.of(helper_user),
            pick(RESPONSE_ACCEPTED, helper_user.ui_lang).format(
                topic=quote(_topic_of(rendered_request=accepted.request), 120),
                student=quote(user.first_name, 64),
                contact=(
                    pick(WRITE_TO, helper_user.ui_lang).format(
                        username=quote(user.tg_username, 64)
                    )
                    if user.tg_username
                    else pick(WAIT_FOR_MESSAGE, helper_user.ui_lang)
                ),
            ),
        )

    [out] = await _responses_out(session, [accepted.response], lang)
    return out


@router.post(
    "/responses/{response_id}/decline",
    response_model=ResponseOut,
    tags=["requests"],
)
async def decline_response(
    response_id: IdPath, session: SessionDep, lang: LangDep, user: UserDep
) -> ResponseOut:
    """Turn one down. Deliberately silent — nobody needs a rejection push."""
    response = await requests_service.decline(session, user=user, response_id=response_id)
    [out] = await _responses_out(session, [response], lang)
    return out


def _topic_of(*, rendered_request: HelpRequest) -> str:
    """A one-line handle on a request, for a notification.

    The text the person typed, not our parse of it — they recognise their own
    words, and "Mathematical Analysis I · ČVUT" is our vocabulary, not theirs.
    """
    return rendered_request.raw_text


async def _axes_line(session, request: HelpRequest) -> str:
    """What the parse made of a request, for the one person watching the first
    of them.

    Slugs and codes rather than translated names, like the profile ping and for
    the same reason: this message is framed in one language whoever posted the
    request wrote in, and a Czech subject name inside a Russian sentence reads
    as a bug. Says so plainly when the parse understood nothing, which is
    itself the interesting case.
    """
    subject = (
        await session.get(Subject, request.subject_id) if request.subject_id else None
    )
    institution = (
        await session.get(Institution, request.institution_id)
        if request.institution_id
        else None
    )
    service = (
        await session.get(ServiceType, request.service_type_id)
        if request.service_type_id
        else None
    )
    named = [
        part
        for part in (
            subject.slug if subject else None,
            institution.code if institution else None,
            service.code if service else None,
        )
        if part
    ]
    return " · ".join(named) if named else OWNER_NOTHING_PARSED


def _price_line(price: Price | None) -> str:
    if price is None or price.amount is None:
        return ""
    return money(price.amount, price.currency)


async def _responses_out(
    session, responses: list[RequestResponse], lang
) -> list[ResponseOut]:
    """Render answers with their authors, in a fixed number of queries."""
    if not responses:
        return []

    helper_ids = {r.helper_id for r in responses}
    rows = (
        await session.execute(
            select(User, HelperProfile)
            .join(HelperProfile, HelperProfile.user_id == User.id)
            .where(User.id.in_(helper_ids))
        )
    ).all()
    people = {user.id: (user, profile) for user, profile in rows}

    out = []
    for response in responses:
        found = people.get(response.helper_id)
        if found is None:
            # The profile was deleted between answering and reading. The row
            # survives by foreign key, but there is nobody left to show.
            continue
        person, profile = found
        out.append(
            ResponseOut(
                id=response.id,
                request_id=response.request_id,
                helper_id=response.helper_id,
                name=full_name(person),
                avatar=avatar_for(person),
                username=person.tg_username,
                affiliation=profile.headline,
                rating=float(profile.rating) if profile.rating is not None else None,
                deals_count=profile.deals_count,
                message=response.message,
                price=(
                    Price(
                        amount=float(response.price_amount),
                        currency=response.price_currency,
                        unit=response.price_unit or PriceUnit.HOUR,
                    )
                    if response.price_amount is not None
                    else None
                ),
                status=response.status.value,
                created_at=response.created_at,
            )
        )
    return out


@router.post(
    "/requests/{request_id}/close",
    response_model=RequestOut,
    tags=["requests"],
)
async def close_request(
    request_id: IdPath, session: SessionDep, lang: LangDep, user: UserDep
) -> RequestOut:
    """Stop taking answers."""
    request = await requests_service.close(session, user=user, request_id=request_id)
    return await _request_out(session, request, lang)


@router.delete(
    "/requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["requests"],
)
async def delete_request(request_id: IdPath, session: SessionDep, user: UserDep) -> None:
    """Remove a request and its answers for good."""
    await requests_service.delete(session, user=user, request_id=request_id)


async def _request_out(session, request: HelpRequest, lang) -> RequestOut:
    [out] = await _requests_out(session, [request], lang)
    return out


async def _requests_out(
    session, requests: list[HelpRequest], lang, *, count_seeing: bool = True
) -> list[RequestOut]:
    """Render a whole page of requests in a fixed number of queries.

    Done per request this was five round trips each — 250 for a full page —
    and every one of them was fetching the same handful of subject and
    faculty names over and over.
    """
    if not requests:
        return []

    subjects = await rows_by_id(session, Subject, (r.subject_id for r in requests))
    institutions = await rows_by_id(
        session, Institution, (r.institution_id for r in requests)
    )
    services = await rows_by_id(
        session, ServiceType, (r.service_type_id for r in requests)
    )

    request_ids = [r.id for r in requests]
    counts = dict(
        (
            await session.execute(
                select(RequestResponse.request_id, func.count(RequestResponse.id))
                .where(RequestResponse.request_id.in_(request_ids))
                .group_by(RequestResponse.request_id)
            )
        ).all()
    )
    responder_rows = (
        await session.execute(
            select(RequestResponse.request_id, User)
            .join(User, User.id == RequestResponse.helper_id)
            .where(RequestResponse.request_id.in_(request_ids))
            .order_by(RequestResponse.request_id, RequestResponse.id)
        )
    ).all()
    responders: dict[int, list] = {}
    for request_id, responder in responder_rows:
        bucket = responders.setdefault(request_id, [])
        if len(bucket) < 4:
            bucket.append(avatar_for(responder))

    now = datetime.now(UTC)
    # Only the author's own open request asks who else could answer it; the
    # feed has no use for the number.
    seeing = (
        await requests_service.helpers_seeing(
            session, [r for r in requests if _is_live(r, now)]
        )
        if count_seeing
        else {}
    )

    out = []
    for request in requests:
        subject = subjects.get(request.subject_id)
        institution = institutions.get(request.institution_id)
        service = services.get(request.service_type_id)
        out.append(
            RequestOut(
                id=request.id,
                text=request.raw_text,
                subject=translated(subject, lang) if subject else None,
                institution=(short_form(institution, lang) if institution else None),
                service_type=translated(service, lang) if service else None,
                subject_id=request.subject_id,
                service_type_id=request.service_type_id,
                deadline_on=request.deadline_on,
                status=_status_of(request, now),
                responses_count=counts.get(request.id, 0),
                responders=responders.get(request.id, []),
                helpers_seeing=seeing.get(request.id, 0),
                work_format=request.work_format,
                city=request.city,
                created_at=request.created_at,
                expires_at=request.expires_at,
                closed_at=request.closed_at,
            )
        )
    return out


def _is_live(request: HelpRequest, now: datetime) -> bool:
    """`requests_service.live`, for a row already loaded."""
    return request.status is RequestStatus.OPEN and (
        request.expires_at is None or request.expires_at > now
    )


def _status_of(request: HelpRequest, now: datetime) -> str:
    """`expired` for an open request past its deadline: nothing writes it, and
    the author's list has to put it among the closed ones."""
    if request.status is RequestStatus.OPEN and not _is_live(request, now):
        return RequestStatus.EXPIRED.value
    return request.status.value
