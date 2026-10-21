"""The scrape endpoint: Prometheus text, behind a bearer token."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from students_cz.core import metrics

# Out of the published contract (openapi.json): it is for Prometheus, closed by
# its own token and not by an initData.
router = APIRouter(include_in_schema=False)


@router.get("/internal/metrics")
async def scrape(authorization: Annotated[str | None, Header()] = None) -> Response:
    # 404 while unconfigured: nothing here to find, whoever asks.
    if not metrics.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not metrics.authorized(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)
