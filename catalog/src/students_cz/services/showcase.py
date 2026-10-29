"""The paid places on the home screen, under «Документы и жизнь».

A card is an ordinary placement in the `home_life` slot, its service in
`conditions.service_type`, so the impressions and clicks are counted, listed
and billed as every other partner card's are. What the showcase adds is a
lifecycle: a card starts as a draft nobody sees, goes live when published,
and comes down when unpublished or when its `until` passes, which frees the
place without anybody doing anything. Nothing is deleted: a card taken down
keeps its numbers and its photo. See docs/showcase-api.md.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import (
    Partner,
    PartnerOffer,
    PartnerOfferI18n,
    PartnerPhoto,
    Placement,
    PlacementEvent,
    ServiceType,
)
from students_cz.db.models.enums import PlacementEventKind, PlacementSlot, UiLang
from students_cz.schemas import (
    AdminShowcaseCard,
    ShowcaseCardIn,
    ShowcaseCardOut,
    ShowcaseCardPatch,
    ShowcaseSlotOut,
    ShowcaseStatus,
)
from students_cz.services.admin import partner_named
from students_cz.services.errors import Conflict, Invalid, NotFound
from students_cz.services.placements import offer_text

# The places, in the order the screen draws them: the first is the big one.
# Azamat's pick on the showcase page (2026-10-29). Translation and housing keep
# their ordinary tiles.
SLOTS = ("bank_letter", "insurance", "residence")

# What a cover may be. Checked by its first bytes, not by what the upload
# claims to be: the bytes are what a phone will be handed.
PHOTO_MAX_BYTES = 2 * 1024 * 1024
_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}

_SLOT = PlacementSlot.HOME_LIFE
_MONTH = timedelta(days=30)


def _status(placement: Placement, now: datetime) -> ShowcaseStatus:
    if placement.published_at is None:
        return "draft"
    if not placement.is_active:
        return "unpublished"
    until = placement.offer.valid_to
    if until is not None and until <= now:
        return "expired"
    return "published"


def _live(placement: Placement, now: datetime) -> bool:
    return _status(placement, now) == "published"


def _service(placement: Placement) -> str:
    return str(placement.conditions.get("service_type", ""))


def _card(placement: Placement, lang: UiLang) -> ShowcaseCardOut:
    offer = placement.offer
    text = offer_text(offer, lang)
    return ShowcaseCardOut(
        id=placement.id,
        service=_service(placement),
        partner=offer.partner.name,
        title=text.title if text else "",
        line=text.subtitle if text else None,
        text=text.context_note if text else None,
        price_from=offer.price_from,
        photo=offer.photo,
        until=offer.valid_to,
        write_to=offer.url,
    )


def _cards():
    return (
        select(Placement)
        .where(Placement.slot == _SLOT)
        .options(
            selectinload(Placement.offer).selectinload(PartnerOffer.partner),
            selectinload(Placement.offer).selectinload(PartnerOffer.texts),
        )
    )


async def _one(session: AsyncSession, card_id: int) -> Placement:
    placement = (
        await session.scalars(
            _cards()
            .where(Placement.id == card_id)
            # A card changed in this session is read again, not from memory.
            .execution_options(populate_existing=True)
        )
    ).first()
    if placement is None:
        raise NotFound("no such showcase card")
    return placement


# ── what students see ───────────────────────────────────────────────────


async def home(
    session: AsyncSession, lang: UiLang, *, viewer_id: int | None
) -> list[ShowcaseSlotOut]:
    """Every place, with its live card or none, each live card counted as seen."""
    now = datetime.now(UTC)
    live: dict[str, Placement] = {}
    # Only cards that went up and stayed up: the rest are history, which only
    # grows. Oldest first, should two ever share a place.
    up = _cards().where(
        Placement.is_active.is_(True), Placement.published_at.is_not(None)
    )
    for placement in (await session.scalars(up.order_by(Placement.id))).all():
        if _live(placement, now):
            live.setdefault(_service(placement), placement)
    for placement in live.values():
        session.add(
            PlacementEvent(
                placement_id=placement.id,
                user_id=viewer_id,
                kind=PlacementEventKind.IMPRESSION,
            )
        )
    return [
        ShowcaseSlotOut(
            service=code,
            card=_card(live[code], lang) if code in live else None,
        )
        for code in SLOTS
    ]


async def card(session: AsyncSession, lang: UiLang, card_id: int) -> ShowcaseCardOut:
    """A live card's page. A draft, or one taken down, is not there."""
    placement = await _one(session, card_id)
    if not _live(placement, datetime.now(UTC)):
        raise NotFound("no such showcase card")
    return _card(placement, lang)


async def photo(session: AsyncSession, sha256: str) -> PartnerPhoto:
    found = await session.get(PartnerPhoto, sha256)
    if found is None:
        raise NotFound("no such photo")
    return found


# ── what the operator does ──────────────────────────────────────────────


async def _admin(session: AsyncSession, lang: UiLang, *where) -> list[AdminShowcaseCard]:
    now = datetime.now(UTC)
    recent = and_(
        PlacementEvent.placement_id == Placement.id,
        PlacementEvent.created_at >= now - _MONTH,
    )
    impressions = func.count(
        case((PlacementEvent.kind == PlacementEventKind.IMPRESSION, 1))
    )
    clicks = func.count(case((PlacementEvent.kind == PlacementEventKind.CLICK, 1)))
    rows = (
        await session.execute(
            _cards()
            .add_columns(impressions, clicks)
            .outerjoin(PlacementEvent, recent)
            .where(*where)
            .group_by(Placement.id)
            .order_by(Placement.id.desc())
            .execution_options(populate_existing=True)
        )
    ).all()
    out = []
    for placement, shown, clicked in rows:
        view = _card(placement, lang)
        out.append(
            AdminShowcaseCard(
                id=placement.id,
                status=_status(placement, now),
                service=view.service,
                partner=view.partner,
                title=view.title,
                line=view.line,
                text=view.text,
                price_from=view.price_from,
                write_to=view.write_to,
                photo=view.photo,
                until=view.until,
                published_at=placement.published_at,
                impressions=shown,
                clicks=clicked,
            )
        )
    return out


async def admin_cards(session: AsyncSession, lang: UiLang) -> list[AdminShowcaseCard]:
    """Every card there has been, newest first."""
    return await _admin(session, lang)


async def admin_card(
    session: AsyncSession, lang: UiLang, card_id: int
) -> AdminShowcaseCard:
    rows = await _admin(session, lang, Placement.id == card_id)
    if not rows:
        raise NotFound("no such showcase card")
    return rows[0]


async def _check_service(session: AsyncSession, code: str) -> None:
    if code not in SLOTS:
        raise Invalid(f"the showcase has places for {', '.join(SLOTS)}")
    known = await session.scalar(
        select(ServiceType.id).where(
            ServiceType.code == code, ServiceType.is_active.is_(True)
        )
    )
    if known is None:
        raise Invalid(f"no active service {code}")


async def create(
    session: AsyncSession, lang: UiLang, card_in: ShowcaseCardIn
) -> AdminShowcaseCard:
    """A draft: saved, previewable, shown to nobody."""
    await _check_service(session, card_in.service)
    partner: Partner = await partner_named(session, card_in.partner)
    offer = PartnerOffer(
        partner_id=partner.id,
        url=card_in.write_to,
        price_from=card_in.price_from,
        valid_to=card_in.until,
        # Live only through the placement: the offer is this card's alone.
        is_active=True,
    )
    session.add(offer)
    await session.flush()
    session.add(
        PartnerOfferI18n(
            offer_id=offer.id,
            lang=lang,
            title=card_in.title,
            subtitle=card_in.line or None,
            context_note=card_in.text or None,
        )
    )
    placement = Placement(
        offer_id=offer.id,
        slot=_SLOT,
        conditions={"service_type": card_in.service},
        is_active=False,
    )
    session.add(placement)
    await session.flush()
    return await admin_card(session, lang, placement.id)


async def update(
    session: AsyncSession, lang: UiLang, card_id: int, change: ShowcaseCardPatch
) -> AdminShowcaseCard:
    """Only the fields sent. `line`, `text` and `price_from` can be cleared
    with a null; the rest a card cannot be without."""
    placement = await _one(session, card_id)
    offer = placement.offer
    sent = change.model_fields_set
    for required in ("partner", "title", "write_to", "until"):
        if required in sent and getattr(change, required) is None:
            raise Invalid(f"a card cannot be without {required}")

    if (
        change.until is not None
        and placement.is_active
        and placement.published_at is not None
    ):
        # A later `until` brings an expired card back up, into a place
        # somebody may have taken since.
        await _claim(session, placement, datetime.now(UTC))
    if change.partner is not None:
        partner = await partner_named(session, change.partner)
        offer.partner_id = partner.id
    if change.write_to is not None:
        offer.url = change.write_to
    if change.until is not None:
        offer.valid_to = change.until
    if "price_from" in sent:
        offer.price_from = change.price_from

    text = next((t for t in offer.texts if t.lang == lang), None)
    if text is None:
        # The first edit in a language the card has no text in starts from
        # the text it has, so a reader of either sees the whole card.
        first = offer_text(offer, lang)
        text = PartnerOfferI18n(
            offer_id=offer.id,
            lang=lang,
            title=first.title if first else "",
            subtitle=first.subtitle if first else None,
            context_note=first.context_note if first else None,
        )
        session.add(text)
    if change.title is not None:
        text.title = change.title
    if "line" in sent:
        text.subtitle = change.line or None
    if "text" in sent:
        text.context_note = change.text or None
    await session.flush()
    return await admin_card(session, lang, card_id)


async def set_photo(
    session: AsyncSession, lang: UiLang, card_id: int, mime: str, content: bytes
) -> AdminShowcaseCard:
    """A new cover. The old one stays in the table, as everything here does."""
    placement = await _one(session, card_id)
    if mime not in _MAGIC:
        raise Invalid("a photo is a JPEG, PNG or WebP")
    if not content:
        raise Invalid("the photo is empty")
    if len(content) > PHOTO_MAX_BYTES:
        raise Invalid("a photo is at most 2 MB")
    if not content.startswith(_MAGIC[mime]) or (
        mime == "image/webp" and content[8:12] != b"WEBP"
    ):
        raise Invalid(f"these bytes are not {mime}")
    sha256 = hashlib.sha256(content).hexdigest()
    if await session.get(PartnerPhoto, sha256) is None:
        session.add(PartnerPhoto(sha256=sha256, mime=mime, content=content))
        await session.flush()
    placement.offer.photo = sha256
    await session.flush()
    return await admin_card(session, lang, card_id)


async def preview(session: AsyncSession, lang: UiLang, card_id: int) -> ShowcaseCardOut:
    """The card exactly as a student will read it, whatever its state, and
    counted as nobody seeing it."""
    return _card(await _one(session, card_id), lang)


async def publish(session: AsyncSession, lang: UiLang, card_id: int) -> AdminShowcaseCard:
    """Live now, if its place is free and it has what the card draws."""
    placement = await _one(session, card_id)
    now = datetime.now(UTC)
    offer = placement.offer
    if offer.photo is None:
        raise Invalid("add a photo first: the card is drawn around it")
    if offer.valid_to is None or offer.valid_to <= now:
        raise Invalid("`until` has passed: set a later one first")
    await _claim(session, placement, now)
    placement.is_active = True
    if placement.published_at is None:
        placement.published_at = now
    await session.flush()
    return await admin_card(session, lang, card_id)


async def _claim(session: AsyncSession, placement: Placement, now: datetime) -> None:
    """A 409 unless the card's place is free of every other live card.

    The place's cards are locked in one order, so two cards going up into it
    cannot both see it free, nor wait on each other for ever. `NO KEY UPDATE`
    rather than `UPDATE`: an impression or a click inserted meanwhile takes a
    key-share lock on its card, and must not wait for this.
    """
    service = _service(placement)
    cards = (
        await session.scalars(
            _cards()
            .where(Placement.conditions["service_type"].astext == service)
            .order_by(Placement.id)
            .with_for_update(of=Placement, key_share=True)
        )
    ).all()
    taken = next((p for p in cards if p.id != placement.id and _live(p, now)), None)
    if taken is not None:
        raise Conflict(
            f"the {service} place is taken by card {taken.id} until "
            f"{taken.offer.valid_to:%Y-%m-%d}; unpublish it first"
        )


async def unpublish(
    session: AsyncSession, lang: UiLang, card_id: int
) -> AdminShowcaseCard:
    """Down now. The card and its numbers stay; publishing again restores it."""
    placement = await _one(session, card_id)
    placement.is_active = False
    await session.flush()
    return await admin_card(session, lang, card_id)
