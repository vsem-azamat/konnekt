"""The helper profile rules, reached without an HTTP client.

This is the point of the service layer and the reason the extraction was
worth doing: the publish state machine and the offer diff are the riskiest
write in the application, and until now the only way to exercise either was a
signed request against a running app.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.db.models import HelperProfile, Offer, ServiceType, User
from students_cz.db.models.enums import PublishStatus, UiLang, WorkFormat
from students_cz.schemas import HelperUpsert, OfferIn
from students_cz.services import errors, helpers

pytestmark = pytest.mark.asyncio


async def _person(session: AsyncSession, tg_id: int) -> User:
    user = User(tg_id=tg_id, first_name="Marek", ui_lang=UiLang.RU)
    session.add(user)
    await session.flush()
    return user


async def test_a_banned_profile_cannot_publish_itself(session: AsyncSession) -> None:
    """Its edits are kept and go to an operator; the ban is theirs to lift."""
    user = await _person(session, 91101)
    helper = HelperProfile(
        user_id=user.id,
        status=PublishStatus.BANNED,
        published_at=datetime.now(UTC),
        reviewed_at=datetime.now(UTC),
    )
    session.add(helper)
    await session.flush()

    saved = await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(about="пусти меня обратно", publish=True),
        lang=UiLang.RU,
    )

    assert saved.published_now is False
    assert helper.status == PublishStatus.BANNED
    assert helper.about == "пусти меня обратно"
    assert helper.reviewed_at is None


async def test_the_same_axes_twice_is_named_rather_than_a_constraint_error(
    session: AsyncSession,
) -> None:
    user = await _person(session, 91102)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "exam_live_help")
    )
    assert service_type_id is not None, "the seed should have this service type"
    offer = OfferIn(service_type_id=service_type_id, price_amount=500)

    with pytest.raises(errors.Invalid) as raised:
        await helpers.save_profile(
            session,
            user=user,
            spec=HelperUpsert(raw_intro="матан", offers=[offer, offer]),
            lang=UiLang.RU,
        )
    assert "duplicate offer" in str(raised.value)


async def test_a_save_that_says_nothing_about_offers_keeps_them(
    session: AsyncSession,
) -> None:
    """`offers` follows the same rule as every other field: omitted is not empty.

    The list has a default of `[]`, so a caller that only wanted to change a
    headline used to delete everything the person offers. Both screens that
    exist today happen to send the list every time, which is the only reason
    this has never happened — and the docstring on `save_profile` already
    promises the opposite.
    """
    user = await _person(session, 91104)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "writing")
    )
    assert service_type_id is not None, "the seed should have this service type"

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service_type_id, price_amount=4000)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(headline="ČVUT FEL"),
        lang=UiLang.RU,
    )
    await session.flush()

    kept = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert [row.service_type_id for row in kept] == [service_type_id]


async def test_an_explicitly_empty_offer_list_still_clears_them(
    session: AsyncSession,
) -> None:
    """The other half of the rule: sent-and-empty means "I have none now"."""
    user = await _person(session, 91105)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "writing")
    )
    assert service_type_id is not None

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service_type_id, price_amount=4000)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session, user=user, spec=HelperUpsert(offers=[]), lang=UiLang.RU
    )
    await session.flush()

    left = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert left == []


async def test_a_service_type_we_withdrew_can_still_be_saved_back(
    session: AsyncSession,
) -> None:
    """Deactivating a category must not lock its helpers out of their own form.

    The save is authoritative — anything missing from the list is deleted — so a
    screen has to send back offers it is not editing. Validating only against
    *active* types turned that into a 422 on every save, which is worse than the
    deletion it avoids: the person cannot change a price at all until they
    notice that one row is the reason.

    A type nobody holds is still refused; this only widens the check by what the
    caller already has.
    """
    user = await _person(session, 91106)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "writing")
    )
    assert service is not None

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service.id, price_amount=4000)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    service.is_active = False
    await session.flush()

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(
            offers=[OfferIn(service_type_id=service.id, price_amount=4500)]
        ),
        lang=UiLang.RU,
    )
    await session.flush()

    kept = (await session.scalars(select(Offer).where(Offer.helper_id == user.id))).all()
    assert [(row.service_type_id, row.price_amount) for row in kept] == [
        (service.id, 4500)
    ]


async def test_a_withdrawn_service_type_you_do_not_hold_is_still_refused(
    session: AsyncSession,
) -> None:
    """The border the widening actually runs along.

    An id that never existed is refused by anything; the case worth pinning is
    a real but deactivated type that this caller has no offer for. That is
    exactly one step from what the rule above allows, and it is where a sloppy
    widening would let a withdrawn category back into the catalog.
    """
    user = await _person(session, 91107)
    service = await session.scalar(
        select(ServiceType).where(ServiceType.code == "nostrification")
    )
    assert service is not None
    service.is_active = False
    await session.flush()

    with pytest.raises(errors.Invalid) as raised:
        await helpers.save_profile(
            session,
            user=user,
            spec=HelperUpsert(offers=[OfferIn(service_type_id=service.id)]),
            lang=UiLang.RU,
        )
    assert "unknown service type" in str(raised.value)


async def test_a_save_that_says_nothing_about_the_format_keeps_it(
    session: AsyncSession,
) -> None:
    """`work_format` follows the same rule as every other field.

    It has a default of `both`, so an unconditional write meant a screen that
    only sent a headline would quietly move an online-only tutor to "either
    way" — and put every one of their offers there too, since `_apply_offers`
    copies it onto each row.
    """
    user = await _person(session, 91108)
    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(work_format=WorkFormat.ONLINE),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session, user=user, spec=HelperUpsert(headline="ČVUT FEL"), lang=UiLang.RU
    )
    await session.flush()

    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    assert profile.work_format is WorkFormat.ONLINE


async def test_a_new_offer_takes_the_format_the_profile_already_says(
    session: AsyncSession,
) -> None:
    """A row created without a format follows the profile, not the column default.

    Guarding `work_format` fixed one divergence and could have introduced
    another: the profile keeps `online`, while a new offer added by a caller
    that said nothing about the format would sit on the column's `both`. The
    person would then be online-only on their page and available in person on
    one of their services.
    """
    user = await _person(session, 91109)
    service_type_id = await session.scalar(
        select(ServiceType.id).where(ServiceType.code == "writing")
    )
    assert service_type_id is not None

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(work_format=WorkFormat.ONLINE),
        lang=UiLang.RU,
    )
    await session.flush()

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(offers=[OfferIn(service_type_id=service_type_id)]),
        lang=UiLang.RU,
    )
    await session.flush()

    offer = await session.scalar(select(Offer).where(Offer.helper_id == user.id))
    assert offer is not None
    assert offer.work_format is WorkFormat.ONLINE


async def test_hiding_a_profile_that_was_published_keeps_it_hidden_not_draft(
    session: AsyncSession,
) -> None:
    user = await _person(session, 91103)

    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(raw_intro="матан", publish=True),
        lang=UiLang.RU,
    )
    await helpers.save_profile(
        session,
        user=user,
        spec=HelperUpsert(raw_intro="матан", publish=False),
        lang=UiLang.RU,
    )

    profile = await session.get(HelperProfile, user.id)
    assert profile is not None
    assert profile.status is PublishStatus.HIDDEN
