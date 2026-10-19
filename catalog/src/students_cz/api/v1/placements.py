"""Partner placements: the second revenue line, always labelled as one."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from students_cz.api.deps import IdPath, IdQuery, LangDep, SessionDep, UserDep
from students_cz.db.models import (
    Placement,
)
from students_cz.db.models.enums import (
    PlacementSlot,
)
from students_cz.schemas import (
    PlacementOut,
)
from students_cz.services import placements

router = APIRouter()


@router.get("/placements", response_model=list[PlacementOut], tags=["partners"])
async def placements_for_slot(
    session: SessionDep,
    lang: LangDep,
    user: UserDep,
    slot: PlacementSlot,
    service_type: str | None = None,
    subject_id: IdQuery = None,
    preview: bool = False,
) -> list[PlacementOut]:
    """The partner cards for one slot, each counted as seen unless a preview.

    `preview` can only lower the count, so trusting the client with it costs
    nothing. See docs/architecture.md, «The ads page is a showcase».
    """
    return await placements.for_slot(
        session,
        lang=lang,
        slot=slot,
        context={
            "service_type": service_type,
            "subject_id": subject_id,
            "ui_lang": user.ui_lang.value,
            "month": datetime.now(UTC).month,
            # Impressions are worth nothing without knowing who saw them.
            "user_id": user.id,
        },
        count=not preview,
    )


@router.post(
    "/placements/{placement_id}/click",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["partners"],
)
async def register_click(
    placement_id: IdPath, session: SessionDep, user: UserDep
) -> None:
    """Record that a partner block was followed.

    The id is checked first: the partner is billed per click, so an unknown one
    must be a 404 rather than a foreign-key traceback.
    """
    exists = await session.scalar(
        select(Placement.id).where(Placement.id == placement_id)
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such placement")
    await placements.record(session, placement_id, user.id, kind="click")
