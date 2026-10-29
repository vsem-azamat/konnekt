"""The catalog as a visitor sees it: the home screen, a person, a contact."""

from fastapi import APIRouter, HTTPException, status

from students_cz.api.deps import IdPath, LangDep, SessionDep, UserDep
from students_cz.schemas import (
    ContactOut,
    HelperDetailOut,
    HomeOut,
)
from students_cz.services import catalog, showcase

router = APIRouter()


@router.get("/home", response_model=HomeOut, tags=["catalog"])
async def home(session: SessionDep, lang: LangDep, user: UserDep) -> HomeOut:
    people, things = await catalog.open_home(session, lang, viewer=user)
    places = await showcase.home(session, lang, viewer_id=user.id)
    return HomeOut(people=people, things=things, showcase=places)


@router.get("/helpers/{user_id}", response_model=HelperDetailOut, tags=["catalog"])
async def helper_detail(
    user_id: IdPath, session: SessionDep, lang: LangDep, user: UserDep
) -> HelperDetailOut:
    detail = await catalog.view_helper(session, user_id, lang, viewer=user)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such published profile")
    return detail


@router.post(
    "/helpers/{user_id}/contact",
    response_model=ContactOut,
    tags=["catalog"],
)
async def start_contact(
    user_id: IdPath, session: SessionDep, user: UserDep
) -> ContactOut:
    """Record that someone is about to write, and hand back the link.

    The conversation itself happens in Telegram, where both people already are.
    What we keep is that it started — which is the only honest basis for the
    response times and deal counts shown on a card. Self-reported numbers would
    be worth nothing.
    """
    # Word for word what it was before the rule moved to `catalog.start_contact`:
    # a route's docstring is the operation's description in the OpenAPI
    # document, so rewriting it here would change the contract, and it is
    # addressed to whoever reads /docs rather than to whoever reads this file.
    return await catalog.start_contact(session, viewer=user, helper_id=user_id)
