"""The routes that do not need a Telegram account.

Someone who opens the domain in a browser has no init data, nothing to sign a
request with, and no chat to be answered in. What they get is a redirect into
the bot, derived from the bot's own token so the handle is never hardcoded.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from students_cz.api.deps import HandleDep, SettingsDep
from students_cz.schemas import AdsInfo

router = APIRouter()


@router.get("/open", include_in_schema=False, tags=["public"])
async def open_in_telegram(handle: HandleDep, app: bool = False) -> RedirectResponse:
    """Send a browser to the bot, or with `app` straight into its Mini App.

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
    # `startapp` with no value opens the bot's main Mini App (BotFather's URL).
    target = f"https://t.me/{username}?startapp" if app else f"https://t.me/{username}"
    return RedirectResponse(target, status_code=302)


@router.get("/ads", tags=["public"])
async def ads(settings: SettingsDep) -> AdsInfo:
    """Where the ads page sends a business: a person in Telegram, or nobody.

    Unauthenticated like `/open`, and for the same kind of reason: the answer
    is a public handle that belongs in configuration, not in the bundle.
    """
    contact = settings.ads_contact
    return AdsInfo(contact_url=f"https://t.me/{contact}" if contact else None)
