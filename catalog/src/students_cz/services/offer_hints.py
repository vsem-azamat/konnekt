"""One-tap suggestions on the prices screen: a few prices and a few subjects.

Approved by Azamat on 29 October 2026 (#konnekt 8882). The numbers are ours
for as long as fewer than `ENOUGH` people price a service: on that day the
catalog listed nobody, so there was nothing to take a median of. From
`ENOUGH` people on they are the middle of what people actually ask. People,
not offers: a tutor has an offer per subject, and one with five subjects would
otherwise set everybody's chips alone (the home screen counts people for the
same reason).

None for the «Документы и жизнь» group: its listing is going paid, and an
anchor there would be a price nobody has agreed.
"""

from collections.abc import Iterable, Sequence
from math import floor
from statistics import median, quantiles

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import HelperProfile, Offer, ServiceType, Subject
from students_cz.db.models.enums import (
    NodeKind,
    PriceUnit,
    PublishStatus,
    ServiceGroup,
    UiLang,
)
from students_cz.schemas import SubjectHintOut
from students_cz.services.naming import translated

ENOUGH = 5

# By the shape of the form, with what the numbers are per: a lesson by the
# hour, a written work by the job, an errand by the item. The unit travels
# with the chips: the errands that get them (nostrification, help on the day
# of an exam) default to the hour in the catalog, and the approved numbers are
# per item.
OURS: dict[str, tuple[list[int], PriceUnit]] = {
    "lesson": ([300, 400, 500], PriceUnit.HOUR),
    "work": ([1500, 3000, 5000], PriceUnit.WORK),
    "errand": ([300, 500, 1000], PriceUnit.ITEM),
}

_STEM = [
    "matematicka-analyza",
    "linearni-algebra",
    "fyzika-1",
    "mikroekonomie",
    "python",
    "pravdepodobnost-a-statistika",
]

# Most asked first. Slugs, not names: names are per language, and a slug that
# is renamed or withdrawn simply drops out instead of pointing at nothing.
SUBJECTS: dict[str, list[str]] = {
    "tutoring": _STEM,
    "exam_prep": _STEM,
    "language_tutoring": [
        "cestina-b1",
        "cestina-b2",
        "cestina-konverzace",
        "anglictina",
        "nemcina",
    ],
}


def from_prices(prices: Sequence[float], shape: str) -> list[int]:
    """Three chips from one price per person: ours below `ENOUGH` people, the
    quartiles from there on.

    Rounded to 50, half up, so a chip reads like a price somebody would name;
    collapsed when two round to the same number; never 0, which would list the
    service as free.
    """
    ours = list(OURS[shape][0]) if shape in OURS else []
    if len(prices) < ENOUGH:
        return ours
    marks = quantiles(sorted(prices), n=4, method="inclusive")
    out: list[int] = []
    for mark in marks:
        rounded = int(floor(mark / 50 + 0.5) * 50)
        if rounded > 0 and rounded not in out:
            out.append(rounded)
    return out or ours


def unit_for(shape: str) -> PriceUnit | None:
    """What the chips of a form shape are per."""
    return OURS[shape][1] if shape in OURS else None


async def hints_for(
    session: AsyncSession, types: Iterable[ServiceType], lang: UiLang
) -> dict[int, tuple[list[int], list[SubjectHintOut]]]:
    """Price and subject chips for each service type, by its id."""
    types = [t for t in types if t.group_code != ServiceGroup.LIFE]
    if not types:
        return {}

    # Every listed price in one query, in the unit its chips are per: a tutor
    # who prices by the semester says nothing about the hourly rate. Then one
    # price per person, their median, so a tutor with five subjects is one
    # voice.
    units = {t.id: unit_for(t.form_shape.value) for t in types}
    rows = (
        await session.execute(
            select(
                Offer.service_type_id,
                Offer.helper_id,
                Offer.price_unit,
                Offer.price_amount,
            )
            .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
            .where(
                Offer.service_type_id.in_([t.id for t in types]),
                Offer.price_unit.in_({u for u in units.values() if u is not None}),
                Offer.is_active.is_(True),
                Offer.price_amount.is_not(None),
                Offer.price_amount > 0,
                HelperProfile.status == PublishStatus.PUBLISHED,
            )
        )
    ).all()
    per_person: dict[int, dict[int, list[float]]] = {}
    for type_id, helper_id, unit, amount in rows:
        if unit == units[type_id]:
            per_person.setdefault(type_id, {}).setdefault(helper_id, []).append(
                float(amount)
            )
    prices = {
        type_id: [median(amounts) for amounts in people.values()]
        for type_id, people in per_person.items()
    }

    slugs = {slug for t in types for slug in SUBJECTS.get(t.code, [])}
    subjects = (
        {
            s.slug: s
            for s in (
                await session.scalars(
                    select(Subject)
                    # Leaves only, as the search offers: a slug that later becomes
                    # a group must not be a chip.
                    .where(
                        Subject.slug.in_(slugs),
                        Subject.is_active.is_(True),
                        Subject.kind == NodeKind.LEAF,
                    )
                    .options(selectinload(Subject.names))
                )
            ).all()
        }
        if slugs
        else {}
    )

    out: dict[int, tuple[list[int], list[SubjectHintOut]]] = {}
    for t in types:
        chips = [
            SubjectHintOut(
                id=subjects[slug].id,
                slug=slug,
                name=translated(subjects[slug], lang) or slug,
            )
            for slug in SUBJECTS.get(t.code, [])
            if slug in subjects
        ]
        out[t.id] = (from_prices(prices.get(t.id, []), t.form_shape.value), chips)
    return out
