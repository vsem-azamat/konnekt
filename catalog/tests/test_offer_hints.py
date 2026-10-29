"""One-tap suggestions on the prices screen: a few prices and a few subjects.

Ours until enough people price a service to take them from, and none for the
«Документы и жизнь» group, whose listing is going paid.
"""

import pytest
from sqlalchemy import select

from students_cz.db.models import HelperProfile, Offer, ServiceType, Subject
from students_cz.db.models.enums import PublishStatus, UiLang
from students_cz.services.offer_hints import OURS, from_prices, hints_for

from .conftest import auth_header


def test_too_few_people_give_our_own_numbers() -> None:
    assert from_prices([500, 600, 700, 800], "lesson") == [300, 400, 500]
    assert from_prices([], "work") == [1500, 3000, 5000]
    assert from_prices([], "errand") == [300, 500, 1000]


def test_enough_people_give_their_quartiles_rounded_half_up() -> None:
    assert from_prices([400, 450, 500, 600, 800], "lesson") == [450, 500, 600]
    # 425 is half way: up, not to the even 400.
    assert from_prices([425, 425, 425, 425, 425], "lesson") == [450]


def test_a_free_price_is_never_a_chip() -> None:
    # Tapping «0 Kč» would list the service as free.
    assert 0 not in from_prices([20, 20, 30, 30, 40], "errand")


def test_each_shape_says_what_its_numbers_are_per() -> None:
    # The errands that get chips default to the hour in the catalog; the
    # approved numbers are per item, so the unit travels with them.
    assert OURS["lesson"][1] == "hour"
    assert OURS["work"][1] == "work"
    assert OURS["errand"][1] == "item"


@pytest.mark.asyncio
async def test_service_types_carry_price_and_subject_hints(client) -> None:
    body = (
        await client.get("/api/v1/taxonomy/service-types", headers=auth_header(90190))
    ).json()
    by_code = {s["code"]: s for s in body}

    assert by_code["writing"]["price_hint_unit"] == "work"
    assert by_code["nostrification"]["price_hint_unit"] == "item"
    # Going paid: no anchor offered until Azamat says how they are listed.
    assert by_code["insurance"]["price_hints"] == []
    assert by_code["insurance"]["subject_hints"] == []

    tutoring = [hint["slug"] for hint in by_code["tutoring"]["subject_hints"]]
    assert tutoring[:2] == ["matematicka-analyza", "linearni-algebra"]
    names = {hint["slug"]: hint["name"] for hint in by_code["tutoring"]["subject_hints"]}
    assert names["matematicka-analyza"] == "Математический анализ"
    languages = [hint["slug"] for hint in by_code["language_tutoring"]["subject_hints"]]
    assert languages[0] == "cestina-b1"


async def _priced(session, helper_factory, tg_id: int, price: float, **kw):
    return await helper_factory(tg_id=tg_id, service_code="exam_prep", price=price, **kw)


@pytest.mark.asyncio
async def test_the_threshold_counts_people_not_their_offers(
    session, helper_factory
) -> None:
    # Exam prep: no demo offers, so what is inserted here is all there is.
    exam_prep_type = await session.scalar(
        select(ServiceType).where(ServiceType.code == "exam_prep")
    )
    assert exam_prep_type is not None
    existing = await session.scalar(
        select(Offer.id).where(Offer.service_type_id == exam_prep_type.id).limit(1)
    )
    if existing is not None:
        pytest.skip("this database already prices exam prep")

    # Four people, one of them with three offers: still four people.
    people = [await _priced(session, helper_factory, 92200 + i, 1000) for i in range(4)]
    for extra in range(2):
        session.add(
            Offer(
                helper_id=people[0].id,
                service_type_id=exam_prep_type.id,
                institution_id=None,
                subject_id=(
                    await session.scalar(
                        select(Subject.id).where(
                            Subject.slug == ["fyzika-1", "python"][extra]
                        )
                    )
                ),
                price_amount=1000,
                price_unit=exam_prep_type.default_price_unit,
            )
        )
    await session.flush()
    hints = await hints_for(session, [exam_prep_type], UiLang.RU)
    assert hints[exam_prep_type.id][0] == [300, 400, 500]

    # A fifth person tips it over to what people ask.
    await _priced(session, helper_factory, 92210, 1000)
    hints = await hints_for(session, [exam_prep_type], UiLang.RU)
    assert hints[exam_prep_type.id][0] == [1000]


@pytest.mark.asyncio
async def test_only_listed_people_and_their_live_offers_count(
    session, helper_factory
) -> None:
    exam_prep_type = await session.scalar(
        select(ServiceType).where(ServiceType.code == "exam_prep")
    )
    assert exam_prep_type is not None
    if await session.scalar(
        select(Offer.id).where(Offer.service_type_id == exam_prep_type.id).limit(1)
    ):
        pytest.skip("this database already prices exam prep")

    people = [await _priced(session, helper_factory, 92300 + i, 2000) for i in range(5)]
    # One hidden, one with the offer switched off: three people are left.
    hidden = await session.get(HelperProfile, people[0].id)
    assert hidden is not None
    hidden.status = PublishStatus.HIDDEN
    off = await session.scalar(select(Offer).where(Offer.helper_id == people[1].id))
    assert off is not None
    off.is_active = False
    await session.flush()

    hints = await hints_for(session, [exam_prep_type], UiLang.RU)
    assert hints[exam_prep_type.id][0] == [300, 400, 500]
