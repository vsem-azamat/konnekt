"""Reference data — service types, subjects, institutions, languages.

Read-only, translated in the database, and cached hard by the client. Nothing
here belongs to a person.
"""

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from students_cz.api.deps import IdQuery, LangDep, ReaderLangDep, SessionDep, UserDep
from students_cz.db.models import (
    HelperProfile,
    Institution,
    Language,
    Offer,
    ServiceOption,
    ServiceType,
    Subject,
)
from students_cz.db.models.enums import (
    PriceUnit,
    PublishStatus,
)
from students_cz.schemas import (
    InstitutionOut,
    LanguageOut,
    ServiceOptionOut,
    ServiceTypeOut,
    SubjectOut,
)
from students_cz.services.catalog import tone_for
from students_cz.services.lookup import find_subjects
from students_cz.services.naming import translated
from students_cz.services.offer_hints import hints_for, unit_for

router = APIRouter()


def _unit(value: str | None) -> PriceUnit | None:
    """`service_types.default_price_unit` is a plain string column.

    The contract promises an enum, so a value nobody has heard of has to become
    "did not say" rather than a ValueError inside response serialisation, which
    would take the whole taxonomy — and with it every screen — down over one bad
    reference row.
    """
    if value is None:
        return None
    try:
        return PriceUnit(value)
    except ValueError:
        return None


@router.get(
    "/taxonomy/service-types", response_model=list[ServiceTypeOut], tags=["taxonomy"]
)
async def service_types(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[ServiceTypeOut]:
    rows = (
        await session.scalars(
            select(ServiceType)
            .where(ServiceType.is_active.is_(True))
            # Group first: the client draws a heading whenever the group
            # changes, and `sort` alone interleaves them — the first seven
            # alternate study and entrance. Ordering by the enum column uses
            # the type's declared order, which is the order the shelves are
            # meant to appear in; `test_home_hands_over_whole_groups` pins it.
            .order_by(ServiceType.group_code, ServiceType.sort)
            .options(
                selectinload(ServiceType.names),
                selectinload(ServiceType.options).selectinload(ServiceOption.names),
            )
        )
    ).all()
    hints = await hints_for(session, rows, lang)
    return [
        ServiceTypeOut(
            id=r.id,
            code=r.code,
            group=r.group_code.value,
            form_shape=r.form_shape.value,
            # The same rule the home screen uses, over the same ordering, so
            # the two agree. Shared rather than repeated for exactly that
            # reason; `test_a_category_keeps_its_colour_across_screens` pins it.
            tone=tone_for(index),
            name=translated(r, lang) or r.code,
            hint=translated(r, lang, "hint"),
            requires_subject=r.requires_subject,
            requires_institution=r.requires_institution,
            default_price_unit=_unit(r.default_price_unit),
            options=[
                ServiceOptionOut(
                    id=option.id,
                    code=option.code,
                    # Falls back to the code rather than to an empty line: a
                    # checkbox with no words is worse than an untranslated one.
                    label=translated(option, lang, "label") or option.code,
                )
                for option in sorted(r.options, key=lambda o: o.sort)
                if option.is_active
            ],
            price_hints=hints.get(r.id, ([], []))[0],
            price_hint_unit=unit_for(r.form_shape.value) if r.id in hints else None,
            subject_hints=hints.get(r.id, ([], []))[1],
        )
        for index, r in enumerate(rows)
    ]


@router.get("/taxonomy/subjects", response_model=list[SubjectOut], tags=["taxonomy"])
async def subjects(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    parent_id: IdQuery = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=300),
) -> list[SubjectOut]:
    """Browse the tree, or search it.

    With `q` the answer comes from fuzzy matching, so "matan" and "матан" both
    work. Without it, one level of the tree is returned.
    """
    if q:
        matches = await find_subjects(session, q, lang, limit=limit, threshold=0.4)
        ids = [m.id for m in matches]
        if not ids:
            return []
        rows = {
            s.id: s
            for s in (
                await session.scalars(
                    select(Subject)
                    .where(Subject.id.in_(ids))
                    .options(selectinload(Subject.names))
                )
            ).all()
        }
        counts = await _offer_counts(session, ids)
        return [
            SubjectOut(
                id=m.id,
                slug=rows[m.id].slug,
                name=m.label,
                parent_id=rows[m.id].parent_id,
                external_code=rows[m.id].external_code,
                offers_count=counts.get(m.id, 0),
            )
            for m in matches
            if m.id in rows
        ]

    stmt = (
        select(Subject)
        .where(Subject.is_active.is_(True), Subject.parent_id == parent_id)
        .order_by(Subject.sort, Subject.id)
        .options(selectinload(Subject.names))
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    child_counts = {
        parent_id: count
        for parent_id, count in (
            await session.execute(
                select(Subject.parent_id, func.count(Subject.id))
                .where(Subject.parent_id.in_([r.id for r in rows] or [0]))
                .group_by(Subject.parent_id)
            )
        ).all()
    }
    counts = await _offer_counts(session, [r.id for r in rows])
    return [
        SubjectOut(
            id=r.id,
            slug=r.slug,
            name=translated(r, lang) or r.slug,
            parent_id=r.parent_id,
            has_children=child_counts.get(r.id, 0) > 0,
            external_code=r.external_code,
            offers_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


async def _offer_counts(session, subject_ids: list[int]) -> dict[int, int]:
    if not subject_ids:
        return {}
    rows = await session.execute(
        select(Offer.subject_id, func.count(Offer.id))
        .join(HelperProfile, HelperProfile.user_id == Offer.helper_id)
        .where(
            Offer.subject_id.in_(subject_ids),
            Offer.is_active.is_(True),
            HelperProfile.status == PublishStatus.PUBLISHED,
        )
        .group_by(Offer.subject_id)
    )
    return dict(rows.all())


@router.get(
    "/taxonomy/institutions", response_model=list[InstitutionOut], tags=["taxonomy"]
)
async def institutions(session: SessionDep, lang: ReaderLangDep) -> list[InstitutionOut]:
    """The whole list, universities with their faculties nested.

    A couple of hundred rows — cheaper to send once than to paginate, and the
    client can then filter without another round trip.
    """
    rows = (
        await session.scalars(
            select(Institution)
            .where(Institution.is_active.is_(True))
            .order_by(Institution.sort, Institution.id)
            .options(selectinload(Institution.names))
        )
    ).all()

    by_parent: dict[int | None, list[Institution]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    return [
        institution_out(row, lang, by_parent.get(row.id, []))
        for row in by_parent.get(None, [])
    ]


def institution_out(row: Institution, lang, children=()) -> InstitutionOut:
    return InstitutionOut(
        id=row.id,
        code=row.code,
        name=translated(row, lang) or row.code,
        short_name=translated(row, lang, "short_name"),
        city=row.city,
        parent_id=row.parent_id,
        faculties=[institution_out(child, lang) for child in children],
    )


@router.get("/taxonomy/languages", response_model=list[LanguageOut], tags=["taxonomy"])
async def languages(
    session: SessionDep, lang: LangDep, user: UserDep
) -> list[LanguageOut]:
    rows = (
        await session.scalars(
            select(Language)
            .where(Language.is_active.is_(True))
            .order_by(Language.sort)
            .options(selectinload(Language.names))
        )
    ).all()
    return [LanguageOut(code=r.code, name=translated(r, lang) or r.code) for r in rows]
