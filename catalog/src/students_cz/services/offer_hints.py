"""One-tap suggestions on the prices screen: a few prices and a few subjects.

Approved by Azamat on 29 October 2026 (#konnekt 8882). The numbers are ours
for as long as a service has fewer than `ENOUGH` priced offers: on that day
the catalog listed nobody, so there was nothing to take a median of. From
`ENOUGH` on they are the middle of what people actually ask.

None for the «Документы и жизнь» group: its listing is going paid, and an
anchor there would be a price nobody has agreed.
"""

from collections.abc import Iterable, Sequence
from statistics import quantiles

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import HelperProfile, Offer, ServiceType, Subject
from students_cz.db.models.enums import PublishStatus, ServiceGroup, UiLang
from students_cz.schemas import SubjectHintOut
from students_cz.services.naming import translated

ENOUGH = 5

# By the shape of the form, which is also what the price is per: a lesson by
# the hour, a written work by the job, an errand by the item.
OURS: dict[str, list[int]] = {
    "lesson": [300, 400, 500],
    "work": [1500, 3000, 5000],
    "errand": [300, 500, 1000],
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
    """Three chips: ours below `ENOUGH` prices, the quartiles from there on.

    Rounded to 50 so a chip reads like a price somebody would name, and
    collapsed when two quartiles round to the same number.
    """
    if len(prices) < ENOUGH:
        return list(OURS.get(shape, []))
    marks = quantiles(sorted(prices), n=4, method="inclusive")
    out: list[int] = []
    for mark in marks:
        rounded = int(round(mark / 50) * 50)
        if rounded not in out:
            out.append(rounded)
    return out


async def hints_for(
    session: AsyncSession, types: Iterable[ServiceType], lang: UiLang
) -> dict[int, tuple[list[int], list[SubjectHintOut]]]:
    """Price and subject chips for each service type, by its id."""
    types = [t for t in types if t.group_code != ServiceGroup.LIFE]
    if not types:
        return {}

    # Every listed price in one query, per service and in its default unit:
    # a tutor who prices by the semester says nothing about the hourly rate.
    rows = (
        await session.execute(
            select(Offer.service_type_id, Offer.price_unit, Offer.price_amount)
            .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
            .where(
                Offer.service_type_id.in_([t.id for t in types]),
                Offer.is_active.is_(True),
                Offer.price_amount.is_not(None),
                HelperProfile.status == PublishStatus.PUBLISHED,
            )
        )
    ).all()
    prices: dict[int, list[float]] = {}
    units = {t.id: t.default_price_unit for t in types}
    for type_id, unit, amount in rows:
        if unit == units[type_id]:
            prices.setdefault(type_id, []).append(float(amount))

    slugs = {slug for t in types for slug in SUBJECTS.get(t.code, [])}
    subjects = (
        {
            s.slug: s
            for s in (
                await session.scalars(
                    select(Subject)
                    .where(Subject.slug.in_(slugs), Subject.is_active.is_(True))
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
