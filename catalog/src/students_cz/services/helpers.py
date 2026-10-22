"""A helper's own profile: the publish state machine and the offer diff.

The riskiest write in the application, which is why it lives here rather than
in a request handler. Everything it enforces is a rule about the catalog, not
about HTTP, so the bot could offer the same thing tomorrow without any of it
being reimplemented.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import (
    HelperProfile,
    Institution,
    Offer,
    ServiceOption,
    ServiceType,
    Subject,
    User,
)
from students_cz.db.models.enums import (
    ContentLang,
    PublishStatus,
    ServiceForm,
    UiLang,
    UserEventKind,
)
from students_cz.schemas import HelperUpsert
from students_cz.services.errors import Invalid, NotFound
from students_cz.services.people import log_event
from students_cz.services.refs import require_row


@dataclass(frozen=True)
class Saved:
    """What a save leaves behind that the row cannot answer afterwards.

    A profile that was already published looks exactly like one that just went
    out, so whether this save is the one that published it has to be said
    where the transition happens. That is what the owner ping is about, and
    the whole of what anything asks of this return value — the profile itself
    is the caller's own `user`'s, and readable from the session.
    """

    published_now: bool
    # Only when it published just now, and only then worth a query: the codes
    # of what this person offers, for the line the owner is pinged with.
    services: tuple[str, ...] = ()


async def save_profile(
    session: AsyncSession, *, user: User, spec: HelperUpsert, lang: UiLang
) -> Saved:
    """Create or replace the caller's helper profile and its offers.

    The set of offers is authoritative — whatever the caller did not send is
    deleted, because a partial update would leave rows behind that the person
    believes they removed. The *rows*, though, are matched on their axes and
    updated in place. Deleting and reinserting was simpler and cost every past
    `contacts` row its `offer_id`, which is `ON DELETE SET NULL`: harmless when
    publishing happened once in a lifetime, and not harmless now that the
    cabinet invites someone to fix a price in ten seconds.

    Fields the caller does not carry are left alone — every one of them, checked
    through `model_fields_set` rather than by testing for `None`, because a
    field with a default cannot tell the two apart otherwise. A profile is
    edited by more than one screen, and each sends only what it knows about.

    Does not commit: the caller owns the transaction.
    """
    # Locked for the save: an operator's ban landing between this read and the
    # write below would otherwise be overwritten by the owner's own status.
    # Waiting on the row, the read sees the ban once it commits.
    # populate_existing: a profile this session loaded earlier must be read
    # again, not answered from memory. FOR NO KEY UPDATE, so offers and
    # contacts can still be inserted under it.
    helper = await session.get(
        HelperProfile,
        user.id,
        with_for_update={"key_share": True},
        populate_existing=True,
    )
    if helper is None:
        helper = HelperProfile(user_id=user.id)
        session.add(helper)

    _apply_text(helper, spec, lang)
    # Changed, whatever changed: an operator's «Оставить» or «Вернуть» checks
    # it against what they read, and offers live in their own table, where
    # the row's own `onupdate` never sees them. The clock and not now(), which
    # stands still for the transaction.
    helper.updated_at = func.clock_timestamp()
    # A ban is not something the banned person can lift by pressing publish.
    # What they changed is kept, though, and goes back to an operator, who
    # either lists it again or leaves it hidden: a profile hidden for a wrong
    # price is fixed by fixing the price.
    if helper.status == PublishStatus.BANNED:
        helper.reviewed_at = None
        published_now = False
    else:
        published_now = await _apply_status(session, helper, user, publish=spec.publish)
    await session.flush()
    # Same rule as the text fields, and for the same reason. `offers` defaults
    # to an empty list, so an unconditional call here deletes everything the
    # person offers the moment a screen sends anything else on its own — which
    # is the promise the docstring above already makes.
    if "offers" in spec.model_fields_set:
        await _apply_offers(session, user=user, helper=helper, spec=spec)
    return Saved(
        published_now=published_now,
        services=await _service_codes(session, helper) if published_now else (),
    )


async def _service_codes(session: AsyncSession, helper: HelperProfile) -> tuple[str, ...]:
    """What this profile offers, by code.

    Read here rather than off `helper.offers` in the caller: the relationship
    is not loaded, and a lazy load after the response is a `MissingGreenlet`
    rather than a query. Codes and not translated names — the one person who
    reads this knows them, and resolving names in three tables to report a
    profile is a query nobody is waiting for.
    """
    rows = await session.scalars(
        select(ServiceType.code)
        .join(Offer, Offer.service_type_id == ServiceType.id)
        .where(Offer.helper_id == helper.user_id, Offer.is_active.is_(True))
        .distinct()
        .order_by(ServiceType.code)
    )
    return tuple(rows)


def _apply_text(helper: HelperProfile, spec: HelperUpsert, lang: UiLang) -> None:
    """Write only what the caller actually sent.

    `model_fields_set` distinguishes "omitted" from "explicitly null", which a
    plain assignment cannot: the cabinet sends no headline, and an
    unconditional write there wiped the line under the person's name on every
    card in the catalog the first time they changed a price.
    """
    given = spec.model_fields_set
    if "headline" in given:
        helper.headline = spec.headline
    if "about" in given:
        helper.about = spec.about
    if "city" in given:
        helper.city = spec.city
    if "place_note" in given:
        helper.place_note = spec.place_note
    helper.raw_intro = spec.raw_intro or helper.raw_intro
    helper.about_lang = ContentLang(lang.value)
    # `work_format` has a default of `both`, so writing it unconditionally
    # moved an online-only tutor to "either way" the moment any screen saved
    # anything else — and `_apply_offers` copies it onto every offer, so the
    # change reached each of their rows too.
    if "work_format" in given:
        helper.work_format = spec.work_format


async def _apply_status(
    session: AsyncSession, helper: HelperProfile, user: User, *, publish: bool
) -> bool:
    """Apply the publish flag. Returns whether it went out for the first time."""
    if publish:
        was_published = helper.status == PublishStatus.PUBLISHED
        # Ever, not since the last save: hiding a profile and listing it again
        # is the same profile coming back, and the owner has already been told
        # about it once.
        first_time = helper.published_at is None
        helper.status = PublishStatus.PUBLISHED
        helper.published_at = helper.published_at or datetime.now(UTC)
        if not was_published:
            await log_event(session, user.id, UserEventKind.PROFILE_PUBLISHED)
        return first_time

    # HIDDEN, not DRAFT, once it has been out: "hide me" has to actually take
    # the profile out of the catalog, and the distinction preserves whether
    # anyone has ever seen it.
    helper.status = PublishStatus.HIDDEN if helper.published_at else PublishStatus.DRAFT
    return False


async def _apply_offers(
    session: AsyncSession, *, user: User, helper: HelperProfile, spec: HelperUpsert
) -> None:
    existing = {
        (row.service_type_id, row.subject_id, row.institution_id): row
        for row in (
            await session.scalars(select(Offer).where(Offer.helper_id == user.id))
        ).all()
    }
    # Active types, plus whatever this person already offers.
    #
    # The list is authoritative — anything missing from it is deleted below — so
    # a screen has to send back rows it is not editing, including any whose
    # category we have since withdrawn. Accepting only active types turns that
    # into a 422 on every save, which is worse than the deletion it prevents:
    # the person cannot change a price at all, and nothing on screen says why.
    #
    # Nobody gains a category this way: to hold one at all it had to be active
    # when the offer was first made. Someone who holds a withdrawn type can add
    # rows under it — another subject, say — and that is accepted on purpose;
    # the alternative is a form that half works for them.
    valid_service_ids = set(
        (await session.scalars(select(ServiceType.id).where(ServiceType.is_active))).all()
    ) | {service_type_id for service_type_id, _, _ in existing}

    # Which checklist lines each kind of help owns, for the filter below. One
    # query for the whole save.
    # Every option, active or not. Filtering on `is_active` here would delete a
    # withdrawn line from every offer the next time its owner saved anything —
    # and the whole reason a line is deactivated rather than deleted is that
    # offers keep pointing at it. Hiding it is the read path's job, which
    # `catalog._option_labels` already does.
    options_by_service: dict[int, set[int]] = {}
    for service_id, option_id in (
        await session.execute(select(ServiceOption.service_type_id, ServiceOption.id))
    ).all():
        options_by_service.setdefault(service_id, set()).add(option_id)

    # Which kinds of help are asked when, for the same filter the checklist
    # gets. One query for the whole save.
    writing_service_ids = set(
        (
            await session.scalars(
                select(ServiceType.id).where(ServiceType.form_shape == ServiceForm.WORK)
            )
        ).all()
    )

    seen_axes: set[tuple[int, int | None, int | None]] = set()
    for offer_spec in spec.offers:
        if offer_spec.service_type_id not in valid_service_ids:
            raise Invalid(f"unknown service type {offer_spec.service_type_id}")
        await require_row(session, Subject, offer_spec.subject_id, "subject_id")
        await require_row(
            session, Institution, offer_spec.institution_id, "institution_id"
        )

        axes = (
            offer_spec.service_type_id,
            offer_spec.subject_id,
            offer_spec.institution_id,
        )
        if axes in seen_axes:
            # The same three axes twice violates uq_offers_axes. Saying which
            # entry is duplicated beats a unique-violation traceback.
            raise Invalid(
                f"duplicate offer for service {axes[0]}, subject {axes[1]}, "
                f"institution {axes[2]}"
            )
        seen_axes.add(axes)

        offer = existing.get(axes)
        is_new = offer is None
        if offer is None:
            offer = Offer(
                helper_id=user.id,
                service_type_id=offer_spec.service_type_id,
                subject_id=offer_spec.subject_id,
                institution_id=offer_spec.institution_id,
            )
            session.add(offer)
        offer.price_amount = offer_spec.price_amount
        offer.price_unit = offer_spec.price_unit
        offer.langs = offer_spec.langs or list(user.spoken_langs)
        # Said nothing, changed nothing — the same rule `work_format` follows
        # below, and for the same reason: `OfferIn` defaults the checklist to
        # `[]`, so any caller that saves an offer without mentioning it would
        # erase what the prices screen wrote. Today's client always sends both
        # fields; the guard is what keeps the next one from having to.
        if "option_ids" in offer_spec.model_fields_set:
            # Only the options belonging to this kind of help. A stale client
            # holding yesterday's checklist would otherwise attach insurance's
            # lines to a bank statement, and nothing downstream would notice:
            # the array references nothing, so the labels would simply read as
            # somebody else's.
            # `fromkeys` and not a set: the same line twice would render twice
            # and hand React two children with one key, and the order is the
            # person's own.
            offer.option_ids = list(
                dict.fromkeys(
                    option_id
                    for option_id in offer_spec.option_ids
                    if option_id
                    in options_by_service.get(offer_spec.service_type_id, set())
                )
            )
        # Same rule, same reason as the checklist above: `OfferIn` defaults it
        # to `None`, so an unconditional write moves a writer who said "a week"
        # to "we will agree" on any save that did not mention it. And the same
        # filter: only a written work is asked when, so a turnaround on a lesson
        # is dropped rather than stored — otherwise the profile reads «Срок:
        # неделя» under a service whose form never offered the question.
        if "turnaround_days" in offer_spec.model_fields_set:
            offer.turnaround_days = (
                offer_spec.turnaround_days
                if offer_spec.service_type_id in writing_service_ids
                else None
            )
        if "note" in offer_spec.model_fields_set:
            offer.note = (offer_spec.note or "").strip() or None
        # Same rule: a caller that said nothing about the format is not saying
        # every offer is now "either way". A row being created still needs one,
        # and the profile's is the only answer that cannot contradict it — the
        # column's own default would put a new service in person for somebody
        # whose page says online only.
        if "work_format" in spec.model_fields_set:
            offer.work_format = spec.work_format
        elif is_new:
            offer.work_format = helper.work_format
        # `is_active` is the pause: the catalog, the feed and the counts all
        # read only active offers already.
        if "paused" in offer_spec.model_fields_set:
            offer.is_active = not offer_spec.paused
        elif is_new:
            offer.is_active = True

    dropped = [row.id for axes, row in existing.items() if axes not in seen_axes]
    if dropped:
        await session.execute(delete(Offer).where(Offer.id.in_(dropped)))


async def pause_offer(
    session: AsyncSession, *, user: User, offer_id: int, paused: bool
) -> Offer:
    """Take one offer out of the catalog, or put it back, keeping it whole."""
    offer = await session.get(Offer, offer_id)
    # 404 for someone else's as for a missing one: ids are not to be probed.
    if offer is None or offer.helper_id != user.id:
        raise NotFound("no such offer")
    offer.is_active = not paused
    return offer
