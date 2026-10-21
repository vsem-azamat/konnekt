"""The scrape endpoint: Prometheus text, behind a bearer token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.core import metrics

# Out of the published schema: the console's route sweep reads the schema, and
# this door is closed by its own token rather than by a session.
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
