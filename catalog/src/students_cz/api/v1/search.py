"""One free-text field, and what the catalog makes of it.

`parse` turns a sentence into editable chips and at most one clarifying
question — the rule for that, and the two rows it records, live in
`services/search.py`. `search` runs the axes those chips describe, and writes
nothing.
"""

import time
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from students_cz.api.deps import IdQuery, LangDep, SessionDep, UserDep
from students_cz.db.models import (
    Institution,
    ServiceType,
    Subject,
)
from students_cz.schemas import (
    Chip,
    ParseOut,
    ParseRequest,
    SearchFilters,
    SearchOut,
)
from students_cz.services import catalog, search
from students_cz.services.naming import short_form, translated

router = APIRouter()

# A person searches a few times a minute at most. One worker serves the API, so
# a window kept in memory is the whole picture; a restart forgets it, which
# costs a flooder one minute.
SEARCHES_PER_MINUTE = 30
_recent: dict[int, deque[float]] = {}


def forget_pace() -> None:
    _recent.clear()


async def _paced(user: UserDep) -> None:
    """Turn away a caller past SEARCHES_PER_MINUTE; any Telegram user can call."""
    now = time.monotonic()
    if len(_recent) > 10_000:
        for user_id in [
            u for u, times in _recent.items() if not times or now - times[-1] >= 60
        ]:
            del _recent[user_id]
    times = _recent.setdefault(user.id, deque())
    while times and now - times[0] >= 60:
        times.popleft()
    if len(times) >= SEARCHES_PER_MINUTE:
        wait = int(60 - (now - times[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "slow down",
            headers={"Retry-After": str(wait)},
        )
    times.append(now)


@router.post(
    "/search/parse",
    response_model=ParseOut,
    tags=["search"],
    dependencies=[Depends(_paced)],
)
async def parse_query(
    payload: ParseRequest, session: SessionDep, lang: LangDep, user: UserDep
) -> ParseOut:
    """Read a sentence and show back what we made of it.

    Every call is logged with its parse and result count. Queries that match
    nothing are the ranked list of what the catalog is missing, and the raw
    text next to the parse is what a better parser would be trained on.
    """
    # Unchanged for the reason `browse.start_contact` gives: the docstring is
    # the operation's description in the OpenAPI document. The rule itself is
    # `services/search.describe`.
    return await search.describe(session, lang, viewer=user, text=payload.text)


@router.get(
    "/search", response_model=SearchOut, tags=["search"], dependencies=[Depends(_paced)]
)
async def search_offers(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    subject_id: IdQuery = None,
    institution_id: IdQuery = None,
    service_type_id: IdQuery = None,
    # Finite and in range: `inf` and `nan` reached int() in the filter chips.
    max_price: Annotated[
        float | None, Query(ge=0, le=1_000_000, allow_inf_nan=False)
    ] = None,
    langs: Annotated[
        list[Annotated[str, StringConstraints(max_length=8)]], Query(max_length=20)
    ] = [],  # noqa: B006
    # The literal rather than a string with a pattern: it is the same
    # constraint, it reaches OpenAPI as an enum, and it is the type the
    # catalog's own signature already asks for.
    sort: catalog.SortKey = Query(default="relevance"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> SearchOut:
    total, results = await catalog.search(
        session,
        lang,
        viewer=user,
        subject_id=subject_id,
        institution_id=institution_id,
        service_type_id=service_type_id,
        max_price=max_price,
        langs=langs,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return SearchOut(
        total=total,
        filters=SearchFilters(
            subject_id=subject_id,
            institution_id=institution_id,
            service_type_id=service_type_id,
            max_price=max_price,
            langs=langs,
        ),
        # The same chips the parse screen showed, so the results screen can say
        # what it is filtering on without re-resolving three ids itself.
        chips=await _filter_chips(
            session,
            lang,
            subject_id=subject_id,
            institution_id=institution_id,
            service_type_id=service_type_id,
            max_price=max_price,
        ),
        results=results,
    )


async def _filter_chips(
    session,
    lang,
    *,
    subject_id: int | None,
    institution_id: int | None,
    service_type_id: int | None,
    max_price: float | None,
) -> list[Chip]:
    chips: list[Chip] = []
    if subject_id:
        row = await session.scalar(
            select(Subject)
            .where(Subject.id == subject_id)
            .options(selectinload(Subject.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="subject",
                    label=translated(row, lang) or row.slug,
                    value=row.id,
                )
            )
    if institution_id:
        row = await session.scalar(
            select(Institution)
            .where(Institution.id == institution_id)
            .options(selectinload(Institution.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="institution",
                    label=short_form(row, lang) or row.code,
                    value=row.id,
                )
            )
    if service_type_id:
        row = await session.scalar(
            select(ServiceType)
            .where(ServiceType.id == service_type_id)
            .options(selectinload(ServiceType.names))
        )
        if row:
            chips.append(
                Chip(
                    kind="service_type",
                    label=translated(row, lang) or row.code,
                    value=row.id,
                )
            )
    if max_price is not None:
        chips.append(Chip(kind="budget", label=str(int(max_price)), value=int(max_price)))
    return chips
