"""What the operator reads in the console, and the partner cards they run.

See docs/architecture.md, «The operator reads the catalog and runs the partner cards».
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, case, exists, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload

from students_cz.db.models import HelperProfile, Institution, Offer, ServiceType, User
from students_cz.db.models.enums import (
    PlacementEventKind,
    PlacementSlot,
    PublishStatus,
    RequestStatus,
    UiLang,
)
from students_cz.db.models.ops import SearchQuery
from students_cz.db.models.partners import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    Placement,
    PlacementEvent,
)
from students_cz.db.models.requests import HelpRequest, RequestResponse
from students_cz.schemas import (
    AdminCatalog,
    AdminCounts,
    AdminHide,
    AdminPlacement,
    AdminPlacementIn,
    AdminProfile,
    AdminProfileDetail,
    AdminRequest,
    AdminSearch,
)
from students_cz.services.catalog import display_name
from students_cz.services.errors import Conflict, NotFound
from students_cz.services.naming import names_by_id
from students_cz.services.placements import offer_text
from students_cz.services.requests import live

WEEK = timedelta(days=7)
MONTH = timedelta(days=30)
# Enough to read on a phone; the counts say how long the full lists are.
LIST_CAP = 50
SEARCH_CAP = 20


async def catalog(session: AsyncSession, lang: UiLang) -> AdminCatalog:
    now = datetime.now(UTC)
    new_profile = and_(
        HelperProfile.status == PublishStatus.PUBLISHED,
        HelperProfile.published_at >= now - WEEK,
    )
    # However old: a profile nobody looked at does not leave on its own. A
    # hidden one is back here once its owner changes it (helpers.py).
    to_review = and_(
        HelperProfile.status.in_((PublishStatus.PUBLISHED, PublishStatus.BANNED)),
        HelperProfile.reviewed_at.is_(None),
    )
    hidden = HelperProfile.status == PublishStatus.BANNED
    unanswered = and_(
        live(now), ~exists().where(RequestResponse.request_id == HelpRequest.id)
    )
    failed_search = and_(
        SearchQuery.results_count == 0, SearchQuery.created_at >= now - MONTH
    )
    return AdminCatalog(
        # A hidden one is new again when its owner changed it, not when it
        # first went out.
        profiles=await _new_profiles(
            session,
            lang,
            to_review,
            newest=case(
                (
                    HelperProfile.status == PublishStatus.BANNED,
                    HelperProfile.updated_at,
                ),
                else_=HelperProfile.published_at,
            ),
        ),
        hidden=await _new_profiles(
            session, lang, hidden, newest=HelperProfile.updated_at
        ),
        unanswered=await _unanswered(session, unanswered),
        failed_searches=await _failed_searches(session, failed_search),
        counts=AdminCounts(
            profiles_week=await _count(session, HelperProfile.user_id, new_profile),
            profiles_to_review=await _count(session, HelperProfile.user_id, to_review),
            hidden=await _count(session, HelperProfile.user_id, hidden),
            requests_week=await _count(
                session,
                HelpRequest.id,
                and_(
                    HelpRequest.status != RequestStatus.DRAFT,
                    HelpRequest.created_at >= now - WEEK,
                ),
            ),
            unanswered=await _count(session, HelpRequest.id, unanswered),
            failed_searches=await _count(
                session, func.distinct(_search_key()), failed_search
            ),
        ),
    )


async def _count(
    session: AsyncSession,
    what: ColumnElement[Any] | QueryableAttribute[Any],
    where: ColumnElement[bool],
) -> int:
    return await session.scalar(select(func.count(what)).where(where)) or 0


async def _new_profiles(
    session: AsyncSession,
    lang: UiLang,
    where: ColumnElement[bool],
    *,
    newest: ColumnElement[Any] | QueryableAttribute[Any] = HelperProfile.published_at,
) -> list[AdminProfile]:
    rows = (
        await session.execute(
            select(HelperProfile.published_at, HelperProfile.status, User)
            .join(User, User.id == HelperProfile.user_id)
            .where(where)
            .order_by(newest.desc())
            .limit(LIST_CAP)
        )
    ).all()
    ids = [user.id for _, _, user in rows]
    services = await _services(session, lang, ids)
    return [
        AdminProfile(
            user_id=user.id,
            # As the catalog shows people, since the operator reads them the
            # way anybody browsing does.
            name=display_name(user),
            status=status,
            services=services.get(user.id, []),
            # A hidden profile was listed once, so it has one; a ban from before
            # the console might not.
            published_at=published_at or user.created_at,
        )
        for published_at, status, user in rows
    ]


async def _services(
    session: AsyncSession, lang: UiLang, ids: list[int]
) -> dict[int, list[str]]:
    # What the catalog lists for them: a service switched off is not offered.
    offered = (
        await session.execute(
            select(Offer.helper_id, Offer.service_type_id)
            .where(Offer.helper_id.in_(ids), Offer.is_active.is_(True))
            .order_by(Offer.id)
        )
    ).all()
    names = await names_by_id(
        session, ServiceType, {service for _, service in offered}, lang
    )
    services: dict[int, list[str]] = {}
    for helper_id, service_id in offered:
        listed = services.setdefault(helper_id, [])
        if names.get(service_id) and names[service_id] not in listed:
            listed.append(names[service_id])
    return services


async def _unanswered(
    session: AsyncSession, where: ColumnElement[bool]
) -> list[AdminRequest]:
    rows = await session.scalars(
        select(HelpRequest).where(where).order_by(HelpRequest.created_at).limit(LIST_CAP)
    )
    return [
        AdminRequest(id=row.id, text=row.raw_text, created_at=row.created_at)
        for row in rows
    ]


def _search_key() -> ColumnElement[Any]:
    # The same search typed twice differs in case and stray spaces; the
    # operator wants to know what people looked for, not how they typed it.
    return func.lower(func.btrim(SearchQuery.raw_text))


async def _failed_searches(
    session: AsyncSession, where: ColumnElement[bool]
) -> list[AdminSearch]:
    times = func.count(SearchQuery.id)
    last = func.max(SearchQuery.created_at)
    rows = (
        await session.execute(
            select(func.min(func.btrim(SearchQuery.raw_text)), times, last)
            .where(where)
            .group_by(_search_key())
            .order_by(times.desc(), last.desc())
            .limit(SEARCH_CAP)
        )
    ).all()
    return [AdminSearch(text=text, times=n, last_at=at) for text, n, at in rows]


async def profile(
    session: AsyncSession, lang: UiLang, user_id: int
) -> AdminProfileDetail:
    """One profile, as the console's sheet shows it before an operator acts."""
    helper, user = await _helper(session, user_id)
    services = await _services(session, lang, [user.id])
    institution = None
    if user.institution_id is not None:
        names = await names_by_id(session, Institution, {user.institution_id}, lang)
        institution = names.get(user.institution_id) or None
    return AdminProfileDetail(
        user_id=user.id,
        name=display_name(user),
        status=helper.status,
        headline=helper.headline,
        about=helper.about,
        services=services.get(user.id, []),
        institution=institution,
        published_at=helper.published_at,
        reviewed_at=helper.reviewed_at,
        updated_at=helper.updated_at,
        hidden_reason=helper.hidden_reason,
        hidden_note=helper.hidden_note,
    )


async def keep_profile(
    session: AsyncSession, lang: UiLang, user_id: int, seen: datetime | None = None
) -> AdminProfileDetail:
    """An operator looked and left it as it is: off «Новые анкеты», still listed,
    or still hidden for the reason it was hidden."""
    await _moderate(
        session,
        user_id,
        and_(
            HelperProfile.status.in_((PublishStatus.PUBLISHED, PublishStatus.BANNED)),
            _as_read(seen),
        ),
        reviewed_at=func.now(),
    )
    return await profile(session, lang, user_id)


async def hide_profile(
    session: AsyncSession, lang: UiLang, user_id: int, why: AdminHide
) -> AdminProfileDetail:
    """Out of the catalog, and its owner cannot list it again; see helpers.py.

    Only a listed profile: «Вернуть» lists it again, which must not undo an
    owner's own «hide me» or publish a draft nobody finished.
    """
    await _moderate(
        session,
        user_id,
        HelperProfile.status == PublishStatus.PUBLISHED,
        status=PublishStatus.BANNED,
        reviewed_at=func.now(),
        hidden_reason=why.reason,
        hidden_note=why.note,
    )
    return await profile(session, lang, user_id)


async def restore_profile(
    session: AsyncSession, lang: UiLang, user_id: int, seen: datetime | None = None
) -> AdminProfileDetail:
    """Listed again, as it was when it was hidden. A profile banned before it
    was ever out gets its first publication now, so the owner's next save is
    not taken for one and announced."""
    await _moderate(
        session,
        user_id,
        and_(HelperProfile.status == PublishStatus.BANNED, _as_read(seen)),
        status=PublishStatus.PUBLISHED,
        published_at=func.coalesce(HelperProfile.published_at, func.now()),
        # Restoring an edited one is a look at the edit: off «Новые анкеты»,
        # and its owner is not told it is still on review.
        reviewed_at=func.now(),
        hidden_reason=None,
        hidden_note=None,
    )
    return await profile(session, lang, user_id)


def _as_read(seen: datetime | None) -> ColumnElement[bool]:
    """Unchanged since the operator read it, when they say when that was."""
    return true() if seen is None else HelperProfile.updated_at == seen


async def _moderate(
    session: AsyncSession, user_id: int, only_if: ColumnElement[bool], **values: Any
) -> None:
    """One conditional UPDATE, so the state checked is the state changed.

    Read first and written after, an owner's save landing in between would be
    overwritten: a profile they took down, banned and then «restored» into a
    listing. Blocked on their row instead, the WHERE is read again once they
    commit, and a profile no longer in that state is a 409.
    """
    changed = await session.scalar(
        update(HelperProfile)
        .where(HelperProfile.user_id == user_id, only_if)
        .values(**values)
        .returning(HelperProfile.user_id)
        .execution_options(synchronize_session=False)
    )
    if changed is None:
        await _helper(session, user_id)  # NotFound when there is none at all
        raise Conflict("the profile is not in a state this applies to")
    # The UPDATE went past the session; what it holds is now stale.
    session.expire_all()


async def _helper(session: AsyncSession, user_id: int) -> tuple[HelperProfile, User]:
    row = (
        await session.execute(
            select(HelperProfile, User)
            .join(User, User.id == HelperProfile.user_id)
            .where(HelperProfile.user_id == user_id)
            # Read again, not answered from memory: an owner's save in this
            # session leaves its server-set `updated_at` expired, and an
            # expired attribute is a lazy load an async session cannot do.
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise NotFound("no such profile")
    return row[0], row[1]


async def partners(session: AsyncSession, lang: UiLang) -> list[AdminPlacement]:
    """Every placement with its last month's numbers."""
    return await _placements(session, lang)


async def _placement(
    session: AsyncSession, lang: UiLang, placement_id: int
) -> AdminPlacement:
    """One placement as the list shows it; the caller knows it exists."""
    (row,) = await _placements(session, lang, Placement.id == placement_id)
    return row


async def _placements(
    session: AsyncSession, lang: UiLang, *where: ColumnElement[bool]
) -> list[AdminPlacement]:
    since = datetime.now(UTC) - MONTH
    recent = and_(
        PlacementEvent.placement_id == Placement.id, PlacementEvent.created_at >= since
    )
    impressions = func.count(
        case((PlacementEvent.kind == PlacementEventKind.IMPRESSION, 1))
    )
    clicks = func.count(case((PlacementEvent.kind == PlacementEventKind.CLICK, 1)))
    rows = (
        await session.execute(
            select(Placement, impressions, clicks)
            .outerjoin(PlacementEvent, recent)
            .options(
                selectinload(Placement.offer).selectinload(PartnerOffer.partner),
                selectinload(Placement.offer).selectinload(PartnerOffer.texts),
            )
            .where(*where)
            .group_by(Placement.id)
            .order_by(Placement.is_active.desc(), impressions.desc(), Placement.id)
        )
    ).all()
    return [
        AdminPlacement(
            placement_id=placement.id,
            partner=placement.offer.partner.name,
            title=text.title if (text := offer_text(placement.offer, lang)) else "",
            slot=placement.slot.value,
            is_active=placement.is_active,
            impressions=shown,
            clicks=clicked,
        )
        for placement, shown, clicked in rows
    ]


def _partner_code(name: str, taken: set[str]) -> str:
    """A stable, readable key for a partner, unique among the ones there are."""
    import re
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48] or "partner"
    code, n = base, 2
    while code in taken:
        code, n = f"{base}-{n}", n + 1
    return code


async def partner_named(session: AsyncSession, name: str) -> Partner:
    """The partner of that name ignoring case, made if there is none, so a
    second card for the same company does not make a second company."""
    partner = (
        await session.scalars(
            select(Partner)
            .where(func.lower(Partner.name) == name.lower())
            .order_by(Partner.id)
        )
    ).first()
    if partner is None:
        taken = set((await session.scalars(select(Partner.code))).all())
        partner = Partner(code=_partner_code(name, taken), name=name)
        session.add(partner)
        await session.flush()
    return partner


async def create_placement(
    session: AsyncSession, lang: UiLang, card: AdminPlacementIn
) -> AdminPlacement:
    """A card on the Life screen.

    The text is stored in the operator's language, and readers in another see
    it as the first text the card has.
    """
    partner = await partner_named(session, card.partner)
    offer = PartnerOffer(
        partner_id=partner.id, url=card.url, logo_text=card.logo_text or None
    )
    session.add(offer)
    await session.flush()
    session.add(
        PartnerOfferI18n(
            offer_id=offer.id,
            lang=lang,
            title=card.title,
            subtitle=card.subtitle or None,
            price_text=card.price_text or None,
            context_note=card.context_note or None,
        )
    )
    # First on the screen: a slot shows three, and the operator must see the
    # card they just added.
    top = await session.scalar(
        select(func.max(Placement.priority)).where(
            Placement.slot == PlacementSlot.SCREEN_LIFE
        )
    )
    placement = Placement(
        offer_id=offer.id, slot=PlacementSlot.SCREEN_LIFE, priority=(top or 0) + 1
    )
    session.add(placement)
    await session.flush()
    return await _placement(session, lang, placement.id)


async def set_placement_active(
    session: AsyncSession, lang: UiLang, placement_id: int, active: bool
) -> AdminPlacement:
    """On or off; nothing is deleted, so a stopped card keeps its numbers."""
    placement = await session.get(Placement, placement_id)
    if placement is None:
        raise NotFound("no such placement")
    if placement.slot == PlacementSlot.HOME_LIFE:
        # A showcase card goes live only through its publish, which keeps one
        # card to a place; a switch here would put a second one up beside it.
        raise Conflict("a showcase card is published through /admin/showcase")
    placement.is_active = active
    await session.flush()
    return await _placement(session, lang, placement_id)
