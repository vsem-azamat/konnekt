"""The catalog's console screens, for the console opened in a browser.

There it has no initData, which is all the catalog takes from a person, so
webapi asks the catalog itself for the super admin its session names, with the
token the two containers share. Each screen is named here: nothing else of the
catalog is reachable this way. See catalog/docs/architecture.md, «The operator
reads the catalog and runs the partner cards».
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import Response

from app.core.config import settings
from app.core.logging import get_logger
from app.webapi.deps import require_super_admin

logger = get_logger("webapi.catalog")

router = APIRouter(prefix="/catalog", tags=["catalog"])

_http: httpx.AsyncClient | None = None

# What the catalog takes as an id: positive and inside bigint.
CatalogId = Annotated[int, Path(ge=1, le=2**63 - 1)]
ConsoleLang = Annotated[Literal["ru", "cs", "en", "uk"] | None, Query(description="The console's language")]
AdminId = Annotated[int, Depends(require_super_admin)]


async def get_catalog_http() -> httpx.AsyncClient:
    """The process's one client to the catalog, made on first use and closed with the app."""
    global _http  # noqa: PLW0603
    if _http is None:
        # Not the environment's proxies: the token goes to the containers'
        # network and nowhere else.
        _http = httpx.AsyncClient(timeout=10, trust_env=False)
    return _http


async def close_catalog_http() -> None:
    global _http  # noqa: PLW0603
    client, _http = _http, None
    if client is not None:
        await client.aclose()


CatalogHttp = Annotated[httpx.AsyncClient, Depends(get_catalog_http)]


async def _ask(
    http: httpx.AsyncClient,
    method: str,
    path: str,
    admin_id: int,
    lang: str | None,
    body: dict[str, Any] | None = None,
) -> Response:
    """One call to the catalog, as `admin_id`; its answer comes back as it was.

    Nothing of the browser's request goes along: not the cookie, not its
    headers. A 401 from the catalog means the containers disagree about the
    token, not that the browser's session ended, so it is not passed on as one.
    """
    token = settings.webapi.catalog_service_token.get_secret_value()
    if not token:
        raise HTTPException(status_code=503, detail="catalog not connected")
    headers = {"X-Catalog-Service": token, "X-Catalog-Operator": str(admin_id)}
    if lang:
        headers["X-Catalog-Lang"] = lang
    url = settings.webapi.catalog_url.rstrip("/") + "/api/v1" + path
    try:
        answer = await http.request(method, url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.warning("catalog_unreachable", path=path, error=type(exc).__name__)
        raise HTTPException(status_code=502, detail="catalog unreachable") from exc
    if answer.status_code == 401:
        logger.error("catalog_refused_service_token", path=path)
        raise HTTPException(status_code=502, detail="catalog refused the service token")
    return Response(
        content=answer.content,
        status_code=answer.status_code,
        media_type=answer.headers.get("content-type"),
    )


@router.get("/admin/catalog")
async def read_catalog(http: CatalogHttp, admin_id: AdminId, lang: ConsoleLang = None) -> Response:
    return await _ask(http, "GET", "/admin/catalog", admin_id, lang)


@router.get("/admin/profiles/{user_id}")
async def read_profile(user_id: CatalogId, http: CatalogHttp, admin_id: AdminId, lang: ConsoleLang = None) -> Response:
    return await _ask(http, "GET", f"/admin/profiles/{user_id}", admin_id, lang)


@router.post("/admin/profiles/{user_id}/{action}")
async def moderate_profile(
    user_id: CatalogId,
    action: Literal["review", "hide", "restore"],
    http: CatalogHttp,
    admin_id: AdminId,
    lang: ConsoleLang = None,
) -> Response:
    return await _ask(http, "POST", f"/admin/profiles/{user_id}/{action}", admin_id, lang)


@router.get("/admin/partners")
async def read_partners(http: CatalogHttp, admin_id: AdminId, lang: ConsoleLang = None) -> Response:
    return await _ask(http, "GET", "/admin/partners", admin_id, lang)


@router.post("/admin/placements")
async def create_placement(
    card: Annotated[dict[str, Any], Body()],
    http: CatalogHttp,
    admin_id: AdminId,
    lang: ConsoleLang = None,
) -> Response:
    # The catalog checks the card; this side only carries it.
    return await _ask(http, "POST", "/admin/placements", admin_id, lang, card)


@router.patch("/admin/placements/{placement_id}")
async def switch_placement(
    placement_id: CatalogId,
    change: Annotated[dict[str, Any], Body()],
    http: CatalogHttp,
    admin_id: AdminId,
    lang: ConsoleLang = None,
) -> Response:
    return await _ask(http, "PATCH", f"/admin/placements/{placement_id}", admin_id, lang, change)


@router.get("/taxonomy/institutions")
async def read_institutions(http: CatalogHttp, admin_id: AdminId, lang: ConsoleLang = None) -> Response:
    """The universities a chat's page names."""
    return await _ask(http, "GET", "/taxonomy/institutions", admin_id, lang)
