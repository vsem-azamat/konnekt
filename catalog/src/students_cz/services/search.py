"""What a sentence is understood to mean, and what that leaves behind.

`parser` reads the words; this turns the reading into the screen — chips to
correct, at most one question, a count — and records two things while it does:
an event, and the query itself.

Both rows are deliberate. Queries that match nothing are the ranked list of
what the catalog is missing, and the raw text beside the parse is what a better
parser would be trained on.
"""

import datetime
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from students_cz.db.models import SearchQuery, ServiceType, User
from students_cz.db.models.enums import UiLang, UserEventKind
from students_cz.schemas import (
    AlsoSubject,
    Chip,
    Clarify,
    ClarifyOption,
    ParseOut,
    Phrase,
)
from students_cz.services import catalog, parser
from students_cz.services.lookup import VECTOR_ALSO_FLOOR
from students_cz.services.naming import translated
from students_cz.services.people import log_event


async def describe(
    session: AsyncSession, lang: UiLang, *, viewer: User, text: str
) -> ParseOut:
    """Read a sentence and say back what was made of it."""
    started = time.monotonic()
    parsed = await parser.parse(session, text, lang.value)

    chips: list[Chip] = []
    if parsed.subject:
        chips.append(
            Chip(
                kind="subject",
                label=parsed.subject.label,
                value=parsed.subject.id,
                confidence=round(parsed.subject.score, 2),
            )
        )
    if parsed.institution:
        chips.append(
            Chip(
                kind="institution",
                label=parsed.institution.label,
                value=parsed.institution.id,
                confidence=round(parsed.institution.score, 2),
            )
        )
    service_type_id = None
    if parsed.service_type:
        service = await session.scalar(
            select(ServiceType)
            .where(ServiceType.code == parsed.service_type)
            .options(selectinload(ServiceType.names))
        )
        if service:
            service_type_id = service.id
            chips.append(
                Chip(
                    kind="service_type",
                    label=translated(service, lang) or service.code,
                    value=service.id,
                )
            )
    if parsed.deadline:
        chips.append(
            Chip(
                kind="deadline",
                label=parsed.deadline.isoformat(),
                value=parsed.deadline.isoformat(),
            )
        )
    if parsed.budget_max:
        chips.append(
            Chip(
                kind="budget",
                label=str(int(parsed.budget_max)),
                value=int(parsed.budget_max),
            )
        )

    # Every parsed filter the search can apply, the budget included. Leaving one
    # out counts people this query does not reach, and writes that number into
    # `search_queries`, where a result for a query nobody ran is worse than no
    # row at all. The deadline is the exception that cannot be honoured: there is
    # no date filter to pass it to, so a query saying nothing but a date counts
    # the whole catalog — see docs/data-model.md.
    total, _ = await catalog.search(
        session,
        lang,
        viewer=viewer,
        subject_id=parsed.subject.id if parsed.subject else None,
        institution_id=parsed.institution.id if parsed.institution else None,
        service_type_id=service_type_id,
        max_price=parsed.budget_max,
        limit=1,
    )

    # The same question again within half a minute (a double tap, a retry)
    # is one search, not another pair of rows.
    asked_just_now = await session.scalar(
        select(SearchQuery.id)
        .where(
            SearchQuery.user_id == viewer.id,
            SearchQuery.raw_text == text,
            SearchQuery.created_at
            > func.now() - datetime.timedelta(seconds=_SAME_QUESTION_SECONDS),
        )
        .limit(1)
    )
    if asked_just_now is None:
        await _record(
            session, viewer, text, parsed, total, took=time.monotonic() - started
        )

    return ParseOut(
        chips=chips,
        clarify=_clarify_for(parsed),
        matches=total,
        note=Phrase(code="parse.nothing_recognised") if not chips else None,
        also=_also(parsed),
    )


def _also(parsed: parser.ParsedQuery) -> AlsoSubject | None:
    """The guess the parse would not search by, when it is worth reading.

    Not when it was believed — then it is the subject, and repeating it would be
    the same list twice. Not when it is noise. And not when it conflicts with
    the kind of help, believed or not: a subject that cannot go with what was
    asked for cannot go beside it either, and the list behind it would be empty
    by construction.
    """
    if not parsed.vector or parsed.vector_conflicted:
        return None
    proposed, _ = parsed.vector
    if parsed.subject and parsed.subject.id == proposed.id:
        return None
    if proposed.score < VECTOR_ALSO_FLOOR:
        return None
    return AlsoSubject(subject_id=proposed.id, label=proposed.label)


def _clarify_for(parsed: parser.ParsedQuery) -> Clarify | None:
    """Ask at most one question, and only when it narrows the result.

    If the text already says which kind of help is wanted, there is nothing to
    ask; if it says nothing at all, a question about exam timing would be
    guessing at the wrong thing.
    """
    if parsed.service_type or parsed.unmatched:
        return None
    return Clarify(
        code="clarify.when",
        options=[
            ClarifyOption(code="exam_prep", tone=0),
            ClarifyOption(code="exam_live_help", tone=1),
            ClarifyOption(code="both", tone=5),
        ],
    )


__all__ = ["describe"]


_SAME_QUESTION_SECONDS = 30


async def _record(
    session: AsyncSession,
    viewer: User,
    text: str,
    parsed: parser.ParsedQuery,
    total: int,
    *,
    took: float,
) -> None:
    """The two rows a search leaves: the person's event and the query itself."""
    await log_event(session, viewer.id, UserEventKind.SEARCH, text=text, results=total)
    session.add(
        SearchQuery(
            user_id=viewer.id,
            raw_text=text,
            parsed={
                "subject_id": parsed.subject.id if parsed.subject else None,
                "institution_id": (parsed.institution.id if parsed.institution else None),
                "service_type": parsed.service_type,
                "deadline": parsed.deadline.isoformat() if parsed.deadline else None,
                "budget_max": parsed.budget_max,
                # What the embedder proposed, and whether it was believed.
                # Logged even when refused: the two thresholds it is judged by
                # were set by eye, and this is the only place the numbers to
                # replace them can come from.
                "vector": (
                    {
                        "subject_id": parsed.vector[0].id,
                        "score": round(parsed.vector[0].score, 3),
                        "lead": round(parsed.vector[1], 3),
                        "used": parsed.subject is not None
                        and parsed.subject.matched_on == "vector",
                    }
                    if parsed.vector
                    else None
                ),
            },
            results_count=total,
            parser="rules.v1",
            took=datetime.timedelta(seconds=took),
        )
    )
