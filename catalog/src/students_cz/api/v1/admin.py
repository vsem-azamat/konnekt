"""What the operator reads in the console, and the partner cards they run.

See services/admin.py.
"""

from fastapi import APIRouter, status

from students_cz.api.deps import AdminDep, IdPath, LangDep, SessionDep
from students_cz.schemas import (
    AdminCatalog,
    AdminPlacement,
    AdminPlacementIn,
    AdminPlacementSwitch,
)
from students_cz.services import admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/catalog", response_model=AdminCatalog)
async def read_catalog(_: AdminDep, session: SessionDep, lang: LangDep) -> AdminCatalog:
    return await admin.catalog(session, lang)


@router.get("/partners", response_model=list[AdminPlacement])
async def read_partners(
    _: AdminDep, session: SessionDep, lang: LangDep
) -> list[AdminPlacement]:
    return await admin.partners(session, lang)


@router.post(
    "/placements", response_model=AdminPlacement, status_code=status.HTTP_201_CREATED
)
async def create_placement(
    card: AdminPlacementIn, _: AdminDep, session: SessionDep, lang: LangDep
) -> AdminPlacement:
    return await admin.create_placement(session, lang, card)


@router.patch("/placements/{placement_id}", response_model=AdminPlacement)
async def switch_placement(
    placement_id: IdPath,
    change: AdminPlacementSwitch,
    _: AdminDep,
    session: SessionDep,
    lang: LangDep,
) -> AdminPlacement:
    return await admin.set_placement_active(session, lang, placement_id, change.is_active)
