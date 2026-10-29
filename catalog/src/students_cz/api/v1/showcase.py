"""The paid places on home: what students read, and what the operator runs.

The operator's half has no screen in the console. Cards are made by agents
calling it on the operator's behalf; docs/showcase-api.md is their manual.
See services/showcase.py for the rules.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response, status

from students_cz.api.deps import IdPath, LangDep, OperatorDep, SessionDep, UserDep
from students_cz.schemas import (
    AdminShowcaseCard,
    ShowcaseCardIn,
    ShowcaseCardOut,
    ShowcaseCardPatch,
)
from students_cz.services import showcase

router = APIRouter()

Sha256 = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


@router.get("/showcase/{card_id}", response_model=ShowcaseCardOut, tags=["partners"])
async def read_card(
    card_id: IdPath, session: SessionDep, lang: LangDep, user: UserDep
) -> ShowcaseCardOut:
    """A live card's page. «Написать» is a click on the placement, as for every
    partner card: `POST /placements/{id}/click`, then the card's link."""
    return await showcase.card(session, lang, card_id)


@router.get(
    "/showcase/photos/{sha256}",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
    tags=["partners"],
)
async def read_photo(sha256: Sha256, session: SessionDep) -> Response:
    """A card's photo, without initData: an `<img>` cannot send it.

    The address is the hash of the bytes, so it names this picture for ever
    and is cached as immutable; nobody can reach a photo without its hash,
    which only a card hands out.
    """
    found = await showcase.photo(session, sha256)
    return Response(
        content=found.content,
        media_type=found.mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ── the operator ────────────────────────────────────────────────────────

admin = APIRouter(prefix="/admin/showcase", tags=["admin"])


@admin.get("/cards", response_model=list[AdminShowcaseCard])
async def list_cards(
    operator: OperatorDep, session: SessionDep
) -> list[AdminShowcaseCard]:
    """Every card there has been, newest first, with last month's numbers."""
    return await showcase.admin_cards(session, operator.lang)


@admin.post(
    "/cards", response_model=AdminShowcaseCard, status_code=status.HTTP_201_CREATED
)
async def create_card(
    card: ShowcaseCardIn, operator: OperatorDep, session: SessionDep
) -> AdminShowcaseCard:
    """A draft. Nobody sees it until it is published."""
    return await showcase.create(session, operator.lang, card)


@admin.get("/cards/{card_id}", response_model=AdminShowcaseCard)
async def read_admin_card(
    card_id: IdPath, operator: OperatorDep, session: SessionDep
) -> AdminShowcaseCard:
    return await showcase.admin_card(session, operator.lang, card_id)


@admin.patch("/cards/{card_id}", response_model=AdminShowcaseCard)
async def change_card(
    card_id: IdPath,
    change: ShowcaseCardPatch,
    operator: OperatorDep,
    session: SessionDep,
) -> AdminShowcaseCard:
    """Only the fields sent; a published card shows the change at once."""
    return await showcase.update(session, operator.lang, card_id, change)


@admin.put(
    "/cards/{card_id}/photo",
    response_model=AdminShowcaseCard,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in ("image/jpeg", "image/png", "image/webp")
            },
        }
    },
)
async def put_photo(
    card_id: IdPath,
    request: Request,
    operator: OperatorDep,
    session: SessionDep,
    content_type: Annotated[str, Header()],
) -> AdminShowcaseCard:
    """The cover, as the request's raw body: JPEG, PNG or WebP, at most 2 MB.
    The card crops it to 16:9."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > showcase.PHOTO_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "a photo is at most 2 MB"
        )
    content = await request.body()
    mime = content_type.split(";")[0].strip().lower()
    return await showcase.set_photo(session, operator.lang, card_id, mime, content)


@admin.get("/cards/{card_id}/preview", response_model=ShowcaseCardOut)
async def preview_card(
    card_id: IdPath, operator: OperatorDep, session: SessionDep
) -> ShowcaseCardOut:
    """The card exactly as the Mini App will read it, in any state, counted as
    nobody seeing it. The photo is at `/showcase/photos/{photo}`."""
    return await showcase.preview(session, operator.lang, card_id)


@admin.post("/cards/{card_id}/publish", response_model=AdminShowcaseCard)
async def publish_card(
    card_id: IdPath, operator: OperatorDep, session: SessionDep
) -> AdminShowcaseCard:
    """Live now. 409 while another card holds the place; 422 without a photo
    or with `until` past."""
    return await showcase.publish(session, operator.lang, card_id)


@admin.post("/cards/{card_id}/unpublish", response_model=AdminShowcaseCard)
async def unpublish_card(
    card_id: IdPath, operator: OperatorDep, session: SessionDep
) -> AdminShowcaseCard:
    """Down now. Nothing is deleted; publishing again puts it back."""
    return await showcase.unpublish(session, operator.lang, card_id)


router.include_router(admin)
