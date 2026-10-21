"""The versioned API, assembled from one module per domain.

Every module here owns a slice of the URL space and nothing else: it parses the
request, leans on `students_cz.services` for the rules, and renders a schema from
`students_cz.schemas`. The prefix is declared once, here, so a module cannot
disagree with its neighbours about where it lives.

`health` is deliberately absent from this router — `/healthz` is not part of
the versioned API and must not move when the version does.
"""

from fastapi import APIRouter

from students_cz.api.v1 import (
    admin,
    browse,
    cabinet,
    me,
    metrics,
    placements,
    public,
    requests,
    search,
    taxonomy,
)

router = APIRouter(prefix="/api/v1")

for _module in (
    public,
    me,
    metrics,
    taxonomy,
    search,
    browse,
    cabinet,
    requests,
    placements,
    admin,
):
    router.include_router(_module.router)
