"""Assembling the screens: home, search results, one person's page."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import (
    AvailabilitySlot,
    Contact,
    HelperProfile,
    Institution,
    Offer,
    ServiceOption,
    ServiceType,
    Subject,
    User,
    UserEducation,
)
from students_cz.db.models.enums import PublishStatus, UiLang, UserEventKind
from students_cz.schemas import (
    Avatar,
    ContactOut,
    HelperCardOut,
    HelperDetailOut,
    HomeSection,
    OfferOut,
    Phrase,
    Price,
    Stat,
)
from students_cz.services import errors
from students_cz.services.lookup import held_by
from students_cz.services.naming import rows_by_id, short_form, translated
from students_cz.services.people import log_event

SortKey = Literal["relevance", "price", "available"]

# Tile colours on the client, in a fixed order. The server picks an index so
# the same person, and the same category, keep the same colour on every screen.
TONE_COUNT = 6


def tone_for(index: int) -> int:
    """Which colour the nth tile wears.

    One function rather than `index % TONE_COUNT` written out wherever tiles are
    built: the home screen and the offer screen both draw the same categories,
    and they only agree for as long as the rule is the same in both places.
    """
    return index % TONE_COUNT


def avatar_for(user: User) -> Avatar:
    initials = (user.first_name or "?")[:1].upper()
    if user.last_name:
        initials += user.last_name[:1].upper()
    return Avatar(
        id=user.id,
        initials=initials,
        tone=user.tg_id % TONE_COUNT,
        photo_url=user.photo_url,
    )


async def _option_labels(
    session: AsyncSession, lang: UiLang, ids: set[int]
) -> dict[int, tuple[int, str]]:
    """Checklist labels by id, translated, active ones only.

    One query for a whole page of offers. An option that has been withdrawn is
    simply absent, which is how a retired line stops appearing without anybody
    rewriting the arrays that point at it.

    The catalog's own `sort` comes back with the label, because the array holding
    these ids is in the order somebody tapped the ticks — so without it the same
    lines read in one order on a profile and another on the screen that wrote
    them.
    """
    rows = await rows_by_id(session, ServiceOption, ids)
    # Falls back to the code, the way the taxonomy endpoint does: an option
    # missing a translation would otherwise be offered on the screen that sets
    # it and vanish from the profile that shows it, losing a tick somebody set.
    return {
        row.id: (row.sort, translated(row, lang, "label") or row.code)
        for row in rows.values()
        if row.is_active
    }


async def home_sections(
    session: AsyncSession, lang: UiLang
) -> tuple[list[HomeSection], list[HomeSection]]:
    """The whole home screen in one round trip.

    Counts are of *people*, not offers: a tutor who lists calculus and linear
    algebra is one person to show, and "9" under a category that has four
    tutors would be a lie the moment anyone counted the faces.
    """
    counts = {
        service_type_id: count
        for service_type_id, count in (
            await session.execute(
                select(
                    Offer.service_type_id,
                    func.count(func.distinct(Offer.helper_id)),
                )
                .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
                .where(
                    Offer.is_active.is_(True),
                    HelperProfile.status == PublishStatus.PUBLISHED,
                )
                .group_by(Offer.service_type_id)
            )
        ).all()
    }

    service_types = (
        await session.scalars(
            select(ServiceType)
            .where(ServiceType.is_active.is_(True))
            # Whole groups, in the order the enum declares them. `sort` alone
            # interleaves study and entrance, and the client draws its heading
            # from where the group changes.
            .order_by(ServiceType.group_code, ServiceType.sort)
            .options(selectinload(ServiceType.names))
        )
    ).all()

    avatars = await _sample_avatars(session, [st.id for st in service_types])

    people = [
        HomeSection(
            kind="service_type",
            code=st.code,
            group=st.group_code.value,
            name=translated(st, lang) or st.code,
            hint=translated(st, lang, "hint"),
            tone=tone_for(index),
            count=counts.get(st.id, 0),
            avatars=avatars.get(st.id, []),
        )
        for index, st in enumerate(service_types)
    ]

    # Things — gear to rent, textbooks to buy — are a planned kind of listing
    # with no rows and no screen. The key stays in the response so that adding
    # them is a change to this function and a new screen, rather than also a
    # change to the shape of what every client already parses.
    return people, []


async def _sample_avatars(
    session: AsyncSession, service_type_ids: list[int], per_section: int = 3
) -> dict[int, list[Avatar]]:
    """Top helpers per category, for every category in one query.

    One query rather than one per category, and de-duplicated *before* the
    limit: a helper with two offers in the same category used to consume two
    of the three slots and leave the row looking half-empty.
    """
    if not service_type_ids:
        return {}

    distinct_pairs = (
        select(
            Offer.service_type_id.label("service_type_id"),
            User.id.label("user_id"),
            HelperProfile.deals_count.label("deals_count"),
        )
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .join(User, User.id == HelperProfile.user_id)
        .where(
            Offer.service_type_id.in_(service_type_ids),
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
        .distinct()
        .subquery()
    )
    ranked = (
        select(
            distinct_pairs.c.service_type_id,
            distinct_pairs.c.user_id,
            func.row_number()
            .over(
                partition_by=distinct_pairs.c.service_type_id,
                order_by=(
                    distinct_pairs.c.deals_count.desc(),
                    distinct_pairs.c.user_id,
                ),
            )
            .label("rank"),
        )
        .select_from(distinct_pairs)
        .subquery()
    )

    rows = (
        await session.execute(
            select(ranked.c.service_type_id, User)
            .join(User, User.id == ranked.c.user_id)
            .where(ranked.c.rank <= per_section)
            .order_by(ranked.c.service_type_id, ranked.c.rank)
        )
    ).all()

    out: dict[int, list[Avatar]] = {}
    for service_type_id, user in rows:
        out.setdefault(service_type_id, []).append(avatar_for(user))
    return out


def _offer_query(
    *,
    subject_ids: list[int] | None,
    institution_id: int | None,
    service_type_id: int | None,
    max_price: float | None,
    langs: list[str],
    exclude_helper_id: int | None = None,
):
    stmt = (
        select(Offer)
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .where(
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
    )
    if exclude_helper_id is not None:
        stmt = stmt.where(Offer.helper_id != exclude_helper_id)
    if subject_ids is not None:
        stmt = stmt.where(Offer.subject_id.in_(subject_ids))
    if service_type_id:
        stmt = stmt.where(Offer.service_type_id == service_type_id)
    if institution_id:
        # An offer with no institution is not excluded: a calculus tutor who
        # did not tie themselves to one school can still help at ČVUT. They
        # just rank lower, and the card says why.
        stmt = stmt.where(
            (Offer.institution_id == institution_id) | Offer.institution_id.is_(None)
        )
    if max_price is not None:
        stmt = stmt.where(
            (Offer.price_amount <= max_price) | Offer.price_amount.is_(None)
        )
    if langs:
        stmt = stmt.where(Offer.langs.overlap(langs))
    return stmt


def _has_free_slot():
    """Whether the helper has an availability window still ahead of them."""
    return (
        select(AvailabilitySlot.id)
        .where(
            AvailabilitySlot.helper_id == Offer.helper_id,
            func.upper(AvailabilitySlot.period) > func.now(),
        )
        .exists()
    )


async def helpers_listed(
    session: AsyncSession,
    *,
    subject_id: int | None,
    service_type_id: int | None,
    exclude_helper_id: int,
) -> Select[tuple[int]]:
    """The people `search` would list for these two filters, but one, as a
    query of their ids: counted under a request, and told about it."""
    base = _offer_query(
        subject_ids=await held_by(session, subject_id) if subject_id else None,
        institution_id=None,
        service_type_id=service_type_id,
        max_price=None,
        langs=[],
        exclude_helper_id=exclude_helper_id,
    )
    return base.with_only_columns(Offer.helper_id).distinct()


async def count_helpers(
    session: AsyncSession,
    *,
    subject_id: int | None,
    service_type_id: int | None,
    exclude_helper_id: int,
) -> int:
    """How many people `search` would list for these two filters, but one."""
    listed = await helpers_listed(
        session,
        subject_id=subject_id,
        service_type_id=service_type_id,
        exclude_helper_id=exclude_helper_id,
    )
    return (
        await session.scalar(select(func.count()).select_from(listed.subquery()))
    ) or 0


async def search(
    session: AsyncSession,
    lang: UiLang,
    *,
    viewer: User,
    subject_id: int | None = None,
    institution_id: int | None = None,
    service_type_id: int | None = None,
    max_price: float | None = None,
    langs: list[str] | None = None,
    sort: SortKey = "relevance",
    limit: int = 20,
    offset: int = 0,
    exclude_self: bool = False,
) -> tuple[int, list[HelperCardOut]]:
    """One card per person, ordered in SQL so paging is coherent.

    Three things this has to get right, and each was wrong when it was done
    the obvious way:

    * A person appears once. Matching two of their offers is a reason to rank
      them higher, not to show them twice.
    * Ordering is total. Every sort ends in the offer id, because ties left
      to the planner's discretion make page two overlap page one.
    * Sorting and "cheapest" are computed over the whole result, not over the
      slice already in memory.
    """
    langs = langs or []
    base = _offer_query(
        # A shelf from the parser reading «математика» means what it holds;
        # a leaf holds itself. See `lookup.held_by`.
        subject_ids=await held_by(session, subject_id) if subject_id else None,
        institution_id=institution_id,
        service_type_id=service_type_id,
        max_price=max_price,
        langs=langs,
        exclude_helper_id=viewer.id if exclude_self else None,
    )

    # with_only_columns on the base query, not a count over base.subquery():
    # the latter leaves the aggregate pointing at the outer offers table and
    # silently produces a cartesian product with the subquery.
    total = (
        await session.scalar(
            base.with_only_columns(func.count(func.distinct(Offer.helper_id)))
        )
    ) or 0
    if not total:
        return 0, []

    cheapest = await session.scalar(base.with_only_columns(func.min(Offer.price_amount)))

    # coalesce, not a bare comparison: `institution_id = :x` evaluates to NULL
    # when the offer has none, and Postgres sorts NULLs first under DESC — so
    # the offers that did *not* match were coming out above the ones that did.
    institution_hit = (
        func.coalesce(Offer.institution_id == institution_id, False).desc()
        if institution_id
        else literal(0)
    )

    # One offer per helper: the best-matching, then the cheapest, then by id.
    best_per_helper = (
        base.with_only_columns(Offer.id.label("offer_id"))
        .distinct(Offer.helper_id)
        .order_by(
            Offer.helper_id,
            institution_hit,
            Offer.price_amount.asc().nulls_last(),
            Offer.id,
        )
        .subquery()
    )

    stmt = (
        select(Offer)
        .join(best_per_helper, best_per_helper.c.offer_id == Offer.id)
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .options(
            selectinload(Offer.helper).selectinload(HelperProfile.user),
            selectinload(Offer.helper).selectinload(HelperProfile.availability),
        )
    )

    if sort == "price":
        stmt = stmt.order_by(Offer.price_amount.asc().nulls_last(), Offer.id)
    elif sort == "available":
        stmt = stmt.order_by(
            _has_free_slot().desc(),
            HelperProfile.response_minutes_avg.asc().nulls_last(),
            Offer.id,
        )
    else:
        stmt = stmt.order_by(
            institution_hit,
            HelperProfile.deals_count.desc(),
            HelperProfile.rating.desc().nulls_last(),
            Offer.id,
        )

    offers = (await session.scalars(stmt.limit(limit).offset(offset))).unique().all()

    viewer_institutions = set(
        (
            await session.scalars(
                select(UserEducation.institution_id).where(
                    UserEducation.user_id == viewer.id
                )
            )
        ).all()
    )
    if viewer.institution_id:
        viewer_institutions.add(viewer.institution_id)

    # Not when the search is for one service: the screen is headed with it.
    services = (
        await rows_by_id(session, ServiceType, (o.service_type_id for o in offers))
        if service_type_id is None
        else {}
    )
    subjects = await rows_by_id(session, Subject, (o.subject_id for o in offers))

    return total, [
        _to_card(
            offer,
            lang,
            service=services.get(offer.service_type_id),
            # Nor the subject where it is the one searched for. Card by card: a
            # search for a shelf («математика») covers many, and each card's
            # own is what it adds.
            subject=(
                subjects.get(offer.subject_id)
                if offer.subject_id and offer.subject_id != subject_id
                else None
            ),
            requested_institution_id=institution_id,
            viewer_institutions=viewer_institutions,
            cheapest=float(cheapest) if cheapest is not None else None,
        )
        for offer in offers
    ]


def _to_card(
    offer: Offer,
    lang: UiLang,
    *,
    service: ServiceType | None,
    subject: Subject | None,
    requested_institution_id: int | None,
    viewer_institutions: set[int],
    cheapest: float | None,
) -> HelperCardOut:
    helper = offer.helper
    user = helper.user

    return HelperCardOut(
        user_id=user.id,
        name=display_name(user),
        avatar=avatar_for(user),
        affiliation=helper.headline,
        service=translated(service, lang) if service else None,
        subject=translated(subject, lang) if subject else None,
        price=Price(
            amount=float(offer.price_amount) if offer.price_amount is not None else None,
            currency=offer.price_currency,
            unit=offer.price_unit,
        ),
        reason=_reason(
            offer,
            requested_institution_id=requested_institution_id,
            viewer_institutions=viewer_institutions,
            cheapest=cheapest,
        ),
        availability=_availability(helper),
        rating=float(helper.rating) if helper.rating is not None else None,
        deals_count=helper.deals_count,
        langs=list(offer.langs),
    )


def display_name(user: User) -> str:
    """First name plus an initial — the convention in the mockups.

    Full surnames are neither needed to choose someone nor ours to publish.
    """
    if user.last_name:
        return f"{user.first_name} {user.last_name[:1]}."
    return user.first_name


def _reason(
    offer: Offer,
    *,
    requested_institution_id: int | None,
    viewer_institutions: set[int],
    cheapest: float | None,
) -> Phrase | None:
    """Why this person is in the list.

    Sometimes the honest answer is "they are cheap and have no experience with
    your exam". Saying that is what makes the other rows believable.
    """
    helper = offer.helper

    if requested_institution_id and offer.institution_id == requested_institution_id:
        if helper.deals_count >= 5:
            return Phrase(
                code="reason.same_exam_experience",
                params={"deals": helper.deals_count},
            )
        return Phrase(code="reason.same_institution")

    if requested_institution_id and offer.institution_id is None:
        if offer.price_amount is not None and offer.price_amount == cheapest:
            return Phrase(code="reason.cheapest_but_unproven")
        return Phrase(code="reason.subject_only")

    if offer.institution_id and offer.institution_id in viewer_institutions:
        return Phrase(code="reason.your_faculty")

    if helper.deals_count >= 5:
        return Phrase(code="reason.experience", params={"deals": helper.deals_count})
    return None


def _window(slot: AvailabilitySlot) -> tuple[datetime, datetime]:
    """The two ends of a slot, as two datetimes.

    A `tstzrange` may be unbounded, so both ends are typed as optional — but
    `availability_slots` carries a `period_is_bounded` check constraint that
    refuses such a row. This is where that database guarantee is turned back
    into something the code above can rely on, in one place rather than as a
    None check at every use.
    """
    lower, upper = slot.period.lower, slot.period.upper
    if lower is None or upper is None:  # pragma: no cover — the constraint forbids it
        raise ValueError(f"availability slot {slot.id} is unbounded")
    return lower, upper


def _upcoming(helper: HelperProfile, now: datetime) -> list[datetime]:
    """When this person is next free, earliest first."""
    starts = []
    for slot in helper.availability:
        lower, upper = _window(slot)
        if upper > now:
            starts.append(lower)
    return sorted(starts)


def _availability(helper: HelperProfile) -> Phrase | None:
    upcoming = _upcoming(helper, datetime.now(UTC))
    if upcoming:
        return Phrase(
            code="availability.free_on",
            params={"date": upcoming[0].date().isoformat()},
        )
    if helper.response_minutes_avg:
        return Phrase(
            code="availability.responds_in",
            params={"minutes": helper.response_minutes_avg},
        )
    return None


async def helper_detail(
    session: AsyncSession, user_id: int, lang: UiLang
) -> HelperDetailOut | None:
    helper = await session.scalar(
        select(HelperProfile)
        .where(HelperProfile.user_id == user_id)
        .options(
            selectinload(HelperProfile.user),
            selectinload(HelperProfile.availability),
            selectinload(HelperProfile.offers).selectinload(Offer.helper),
        )
    )
    if helper is None or helper.status != PublishStatus.PUBLISHED:
        return None

    user = helper.user
    offers = await _offers_out(session, helper, lang)

    stats: list[Stat] = []
    if helper.deals_count:
        stats.append(Stat(code="stat.deals", value=str(helper.deals_count)))
    if helper.rating is not None:
        stats.append(Stat(code="stat.rating", value=f"{float(helper.rating):.1f}"))
    if helper.published_at:
        years = (datetime.now(UTC) - helper.published_at).days // 365
        stats.append(
            Stat(code="stat.years" if years else "stat.since", value=str(years or 1))
        )

    free = _upcoming(helper, datetime.now(UTC))[:4]

    return HelperDetailOut(
        user_id=user.id,
        name=display_name(user),
        avatar=avatar_for(user),
        affiliation=helper.headline,
        about=helper.about,
        headline=helper.headline,
        stats=stats,
        offers=offers,
        langs=sorted(
            {lang_code for o in helper.offers if o.is_active for lang_code in o.langs}
        ),
        work_format=helper.work_format,
        place_note=helper.place_note,
        free_slots=free,
        intro_context={
            "name": user.first_name,
            "subjects": ", ".join(sorted({o.subject for o in offers if o.subject})),
        },
        telegram_url=(f"https://t.me/{user.tg_username}" if user.tg_username else None),
    )


async def _offers_out(
    session: AsyncSession, helper: HelperProfile, lang: UiLang
) -> list[OfferOut]:
    if not helper.offers:
        return []

    subjects = await rows_by_id(session, Subject, (o.subject_id for o in helper.offers))
    institutions = await rows_by_id(
        session, Institution, (o.institution_id for o in helper.offers)
    )
    services = await rows_by_id(
        session, ServiceType, (o.service_type_id for o in helper.offers)
    )

    # Every checklist label these offers point at, in one query rather than one
    # per offer. Inactive options are left out: a line withdrawn from the
    # catalog should stop being shown, and the ids stay valid either way.
    labels = await _option_labels(
        session, lang, {oid for offer in helper.offers for oid in offer.option_ids}
    )

    out: list[OfferOut] = []
    for offer in helper.offers:
        if not offer.is_active:
            continue
        service = services.get(offer.service_type_id)
        subject = subjects.get(offer.subject_id) if offer.subject_id else None
        institution = (
            institutions.get(offer.institution_id) if offer.institution_id else None
        )
        out.append(
            OfferOut(
                id=offer.id,
                service_type=service.code if service else "",
                service_type_name=(translated(service, lang) if service else "") or "",
                subject=translated(subject, lang) if subject else None,
                institution=(short_form(institution, lang) if institution else None),
                price=Price(
                    amount=(
                        float(offer.price_amount)
                        if offer.price_amount is not None
                        else None
                    ),
                    currency=offer.price_currency,
                    unit=offer.price_unit,
                ),
                langs=list(offer.langs),
                work_format=offer.work_format,
                # Sorted by the catalog's own order, not by the order the
                # ticks were tapped.
                options=[
                    label
                    for _, label in sorted(
                        labels[oid] for oid in offer.option_ids if oid in labels
                    )
                ],
                note=offer.note,
                turnaround_days=offer.turnaround_days,
            )
        )
    return out


async def open_home(
    session: AsyncSession, lang: UiLang, *, viewer: User
) -> tuple[list[HomeSection], list[HomeSection]]:
    """The home screen, and the fact that somebody opened the app.

    Separate from `home_sections` rather than folded into it: the sections are
    a read the bot may want without claiming anybody opened anything, and this
    is the screen standing in for "opened the app". Logging every request would
    drown that signal in taxonomy fetches.
    """
    sections = await home_sections(session, lang)
    await log_event(session, viewer.id, UserEventKind.APP_OPEN, lang=lang.value)
    return sections


async def view_helper(
    session: AsyncSession, user_id: int, lang: UiLang, *, viewer: User
) -> HelperDetailOut | None:
    """One person's page, and the fact that it was read.

    Nothing is recorded when there is no such page: an event here would count
    views of profiles that do not exist as views of profiles.
    """
    detail = await helper_detail(session, user_id, lang)
    if detail is None:
        return None
    await log_event(session, viewer.id, UserEventKind.HELPER_VIEW, helper_id=user_id)
    return detail


async def start_contact(
    session: AsyncSession, *, viewer: User, helper_id: int
) -> ContactOut:
    """Record that someone is about to write, and hand back the link.

    The conversation itself happens in Telegram, where both people already are.
    What we keep is that it started — which is the only honest basis for the
    response times and deal counts shown on a card. Self-reported numbers would
    be worth nothing.

    `BadRequest` rather than `Invalid` for writing to yourself: it answered 400
    before this moved out of the route, and a status code is not the thing this
    change is allowed to alter.
    """
    if helper_id == viewer.id:
        raise errors.BadRequest("that is your own profile")

    helper = await session.scalar(
        select(HelperProfile)
        .where(HelperProfile.user_id == helper_id)
        .options(selectinload(HelperProfile.user))
    )
    if helper is None or helper.status != PublishStatus.PUBLISHED:
        raise errors.NotFound("no such published profile")
    if not helper.user.tg_username:
        raise errors.Conflict("this person has no public username")

    session.add(Contact(student_id=viewer.id, helper_id=helper_id, intro_text=None))
    await log_event(session, viewer.id, UserEventKind.CONTACT, helper_id=helper_id)

    return ContactOut(telegram_url=f"https://t.me/{helper.user.tg_username}")


__all__ = [
    "avatar_for",
    "helper_detail",
    "home_sections",
    "open_home",
    "search",
    "start_contact",
    "view_helper",
]
