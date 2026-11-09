"""The routes that do not need a Telegram account.

Someone who opens the domain in a browser has no init data, nothing to sign a
request with, and no chat to be answered in. What they get is a redirect into
the bot, derived from the bot's own token so the handle is never hardcoded.
"""

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.api.deps import HandleDep, IdPath, SessionDep, SettingsDep
from students_cz.db.models import Institution
from students_cz.db.models.enums import InstitutionKind, UiLang
from students_cz.schemas import (
    AdsInfo,
    PublicFaculty,
    PublicHelperCard,
    PublicHelperPage,
    PublicUniversity,
)
from students_cz.services import site
from students_cz.services.naming import translated

router = APIRouter()

# «Открыть в Konnekt» on a university's page: the app's own start parameter for
# a university's chats (web/src/lib/startParam.ts), `uni-` and the code.
UNIVERSITY_START = "uni-"
# The code the app accepts after it (INSTITUTION_CODE in web/src/lib/chats.ts).
# Checked before the database is asked: a NUL byte reaches asyncpg as a 500.
_APP_CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# «Написать в Konnekt» on a helper's page on the site: the app's start parameter
# for a profile, `helper-` and the id (web/src/lib/startParam.ts).
HELPER_START = "helper-"
# An id as the database has them: no sign, no leading zero, within a bigint.
_HELPER_ID = re.compile(r"[1-9][0-9]{0,17}")
# Which of the site's buttons was pressed (`site_header`, `site_article_<slug>`):
# passed on as the start parameter, which the Mini App opens nothing for and
# the audience keeps as where somebody came from (app/audience/record.py).
# Only the site's own shape, and no longer than Telegram's 64 characters.
_SITE_SOURCE = re.compile(r"site_[a-z0-9][a-z0-9_-]{0,58}")


def _universities():
    """The active universities, each at the top of the tree."""
    return select(Institution).where(
        Institution.is_active.is_(True),
        Institution.parent_id.is_(None),
        Institution.kind == InstitutionKind.UNIVERSITY,
    )


async def _known_start(session: AsyncSession, start: str | None) -> str | None:
    """`start` when the app has a screen for it, which the catalog can vouch for.

    Only a university the catalog lists, or a helper the site shows: anything
    else would be passed on to Telegram as typed, and a link is not the place
    for the site to guess.
    """
    if start is None:
        return None
    if start.startswith(HELPER_START):
        helper_id = start.removeprefix(HELPER_START)
        if not _HELPER_ID.fullmatch(helper_id):
            return None
        return start if await site.is_on_site(session, int(helper_id)) else None
    if not start.startswith(UNIVERSITY_START):
        return None
    code = start.removeprefix(UNIVERSITY_START)
    if not _APP_CODE.fullmatch(code):
        return None
    found = await session.scalar(
        _universities()
        .where(Institution.code == code)
        .with_only_columns(Institution.code)
    )
    return start if found is not None else None


@router.get("/open", include_in_schema=False, tags=["public"])
async def open_in_telegram(
    handle: HandleDep,
    session: SessionDep,
    app: bool = False,
    start: str | None = None,
    source: Annotated[str | None, Query(alias="from")] = None,
) -> RedirectResponse:
    """Send a browser to the bot, or with `app` straight into its Mini App.

    `start` opens the Mini App on one screen, a university's chats
    (`uni-cvut`) or a helper the site shows (`helper-123`); one the catalog
    does not know opens the app itself. `from`
    says which of the site's buttons it was (`site_header`), for the app to
    record as the source when it opens on no screen.

    Unauthenticated on purpose: this is what the landing page's button points
    at, and the landing is what someone sees who has never opened Telegram
    here. It redirects rather than returning the handle so the handle exists
    in exactly one place — the token the API is already running with. Change
    the bot and nothing in the frontend or the build needs to know.
    """
    username = await handle.username()
    if username is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no bot is configured")
    # 302 rather than 301: a permanent redirect would be cached by the browser
    # for ever, and the target is a handle that can change.
    if (screen := await _known_start(session, start)) is not None:
        return RedirectResponse(
            f"https://t.me/{username}?startapp={screen}", status_code=302
        )
    if app and source is not None and _SITE_SOURCE.fullmatch(source):
        return RedirectResponse(
            f"https://t.me/{username}?startapp={source}", status_code=302
        )
    # `startapp` with no value opens the bot's main Mini App (BotFather's URL).
    opens_app = app or start is not None
    target = (
        f"https://t.me/{username}?startapp" if opens_app else f"https://t.me/{username}"
    )
    return RedirectResponse(target, status_code=302)


@router.get("/ads", tags=["public"])
async def ads(settings: SettingsDep) -> AdsInfo:
    """Where the ads page sends a business: a person in Telegram, or nobody.

    Unauthenticated like `/open`, and for the same kind of reason: the answer
    is a public handle that belongs in configuration, not in the bundle.
    """
    contact = settings.ads_contact
    return AdsInfo(contact_url=f"https://t.me/{contact}" if contact else None)


@router.get("/universities", response_model=list[PublicUniversity], tags=["public"])
async def universities(
    session: SessionDep, settings: SettingsDep, lang: UiLang | None = None
) -> list[PublicUniversity]:
    """The universities, for the public site's catalog pages.

    Unauthenticated like `/open`: the site renders these pages for people who
    are not in Telegram and for search engines, and the rows are the same
    reference data every app user reads. The language is asked for in the
    query, the page's own, since there is nobody whose setting it could be;
    without one, the API's default, as for the console.
    """
    lang = lang or UiLang(settings.default_ui_lang)
    rows = (
        await session.scalars(_universities().order_by(Institution.sort, Institution.id))
    ).all()
    # Every university's faculties in one query, not one per university.
    faculties: dict[int | None, list[PublicFaculty]] = {row.id: [] for row in rows}
    for faculty in await session.scalars(
        select(Institution)
        .where(
            Institution.is_active.is_(True),
            Institution.kind == InstitutionKind.FACULTY,
            Institution.parent_id.in_(faculties),
        )
        .order_by(Institution.sort, Institution.id)
    ):
        faculties[faculty.parent_id].append(
            PublicFaculty(
                code=faculty.code,
                name=translated(faculty, lang) or faculty.code,
                short_name=translated(faculty, lang, "short_name"),
            )
        )
    return [
        PublicUniversity(
            code=row.code,
            name=translated(row, lang) or row.code,
            short_name=translated(row, lang, "short_name"),
            city=row.city,
            site_url=row.site_url,
            faculties=faculties[row.id],
        )
        for row in rows
    ]


@router.get("/public/helpers", response_model=list[PublicHelperCard], tags=["public"])
async def public_helpers(
    session: SessionDep, settings: SettingsDep, lang: UiLang | None = None
) -> list[PublicHelperCard]:
    """The helpers who asked to be on the public site, for its tutors pages.

    Unauthenticated like `/universities`, and only the profiles whose owners
    turned «показывать на konnekt.cz» on: see `services/site.py` for the rest
    of the rule and for what a card leaves out. Reading it records nothing,
    since the reader is anybody, a crawler included.
    """
    return await site.site_helpers(session, lang or UiLang(settings.default_ui_lang))


@router.get("/public/helpers/{user_id}", response_model=PublicHelperPage, tags=["public"])
async def public_helper(
    user_id: IdPath,
    session: SessionDep,
    settings: SettingsDep,
    lang: UiLang | None = None,
) -> PublicHelperPage:
    """One helper's page on the public site, by the id at the end of its slug."""
    page = await site.site_helper(
        session, user_id, lang or UiLang(settings.default_ui_lang)
    )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such helper on the site")
    return page
