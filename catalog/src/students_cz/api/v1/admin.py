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
    AdminProfileDetail,
)
from students_cz.services import admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/catalog", response_model=AdminCatalog)
async def read_catalog(_: AdminDep, session: SessionDep, lang: LangDep) -> AdminCatalog:
    return await admin.catalog(session, lang)


@router.get("/profiles/{user_id}", response_model=AdminProfileDetail)
async def read_profile(
    user_id: IdPath, _: AdminDep, session: SessionDep, lang: LangDep
) -> AdminProfileDetail:
    return await admin.profile(session, lang, user_id)


@router.post("/profiles/{user_id}/review", response_model=AdminProfileDetail)
async def keep_profile(
    user_id: IdPath, _: AdminDep, session: SessionDep, lang: LangDep
) -> AdminProfileDetail:
    return await admin.keep_profile(session, lang, user_id)


@router.post("/profiles/{user_id}/hide", response_model=AdminProfileDetail)
async def hide_profile(
    user_id: IdPath, _: AdminDep, session: SessionDep, lang: LangDep
) -> AdminProfileDetail:
    return await admin.hide_profile(session, lang, user_id)


@router.post("/profiles/{user_id}/restore", response_model=AdminProfileDetail)
async def restore_profile(
    user_id: IdPath, _: AdminDep, session: SessionDep, lang: LangDep
) -> AdminProfileDetail:
    return await admin.restore_profile(session, lang, user_id)


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
