import hmac
import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.core.config import Settings, get_settings
from students_cz.core.security import InitDataError, TelegramIdentity, parse_init_data
from students_cz.db.models import User
from students_cz.db.models.enums import UiLang
from students_cz.db.session import session_scope
from students_cz.services.notify import Notifier
from students_cz.services.people import remember
from students_cz.services.telegram import BotHandle

log = logging.getLogger("students_cz.auth")

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(session_scope, scope="function")]

# A database id as a request may carry one: positive and inside bigint. Past
# that range a value reached asyncpg and came back as a 500, which any session
# could provoke at will.
_BIGINT_MAX = 2**63 - 1
IdPath = Annotated[int, Path(ge=1, le=_BIGINT_MAX)]
IdQuery = Annotated[int | None, Query(ge=1, le=_BIGINT_MAX)]


def _extract_init_data(authorization: str | None) -> str:
    """Read the `Authorization: tma <initData>` header.

    The `tma` scheme is the convention the Telegram SDKs use. initData must not
    travel as a query parameter — it would end up in proxy and access logs.
    """
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Authorization header")
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "expected 'Authorization: tma <initData>'"
        )
    return raw


async def current_identity(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramIdentity:
    try:
        return parse_init_data(_extract_init_data(authorization), settings)
    except InitDataError as exc:
        # The reason goes to the log: told to the caller, it says which check
        # a forged or replayed payload has to beat next.
        log.info("init_data_rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "init data rejected") from exc


IdentityDep = Annotated[TelegramIdentity, Depends(current_identity)]


async def current_user(
    identity: IdentityDep,
    session: SessionDep,
    settings: SettingsDep,
) -> User:
    """Fetch the caller, creating the row on first sight.

    Telegram is the identity provider, so there is no sign-up: the first
    authenticated request is the registration.
    """
    user = await remember(
        session,
        tg_id=identity.tg_id,
        first_name=identity.first_name,
        last_name=identity.last_name,
        username=identity.username,
        language_code=identity.language_code,
        photo_url=identity.photo_url,
        supported_langs=settings.supported_ui_langs,
        source=identity.start_param,
        may_write=identity.may_write,
    )
    # The one write that outlives a failed request, deliberately. Telegram is
    # the identity provider and the first authenticated request is the
    # registration, so first sight of a person — and the `source` that says
    # where they came from — should survive whatever the handler goes on to do
    # with them. It also releases the lock on the users unique index, which the
    # mini app's several parallel opening requests would otherwise queue on.
    await session.commit()

    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account is blocked")
    return user


UserDep = Annotated[User, Depends(current_user)]


async def current_lang(user: UserDep) -> UiLang:
    return user.ui_lang


LangDep = Annotated[UiLang, Depends(current_lang)]


def is_operator(user: User, settings: Settings) -> bool:
    """One of the console's operators. The one place that says so."""
    return user.tg_id in settings.admin_tg_ids


@dataclass(frozen=True)
class Operator:
    """One of the console's operators, and the language the console reads in."""

    tg_id: int
    lang: UiLang


# The console's server, asking for an operator it signed in: a browser has no
# initData. Hidden from the schema, because no client of the contract sends
# them; the Mini App's proxy strips them from what a browser sends.
ServiceHeader = Annotated[
    str | None, Header(alias="X-Catalog-Service", include_in_schema=False)
]
OperatorHeader = Annotated[
    str | None, Header(alias="X-Catalog-Operator", include_in_schema=False)
]
LangHeader = Annotated[
    str | None, Header(alias="X-Catalog-Lang", include_in_schema=False)
]


def _service_operator(
    settings: Settings, token: str, operator: str | None, lang: str | None
) -> Operator:
    """Who the console's server asks for, if it showed the token.

    The token says the call comes from webapi; the operator still has to be on
    `ADMIN_TG_IDS`, because who is an operator is this service's rule. See
    docs/architecture.md, «The operator reads the catalog and runs the partner
    cards».
    """
    expected = settings.service_token.get_secret_value()
    # Unset is off: an empty header must never match an empty setting.
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        log.info("service_call_rejected: token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "service call rejected")
    if (
        not operator
        or not (operator.isascii() and operator.isdigit())
        or int(operator) < 1
    ):
        log.info("service_call_rejected: operator")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "service call rejected")
    tg_id = int(operator)
    if tg_id not in settings.admin_tg_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not an operator")
    try:
        ui_lang = UiLang(lang) if lang else UiLang(settings.default_ui_lang)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown language"
        ) from exc
    return Operator(tg_id=tg_id, lang=ui_lang)


async def current_operator(
    settings: SettingsDep,
    session: SessionDep,
    service: ServiceHeader = None,
    operator: OperatorHeader = None,
    lang: LangHeader = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Operator:
    """The caller, if they are one of the console's operators; 403 otherwise.

    Inside Telegram by initData, like anybody else; from a browser through
    webapi, which shows the service token. A call that shows a token is judged
    by it alone and never falls back to initData.
    """
    if service is not None:
        return _service_operator(settings, service, operator, lang)
    user = await current_user(
        await current_identity(settings, authorization), session, settings
    )
    if not is_operator(user, settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not an operator")
    return Operator(tg_id=user.tg_id, lang=user.ui_lang)


OperatorDep = Annotated[Operator, Depends(current_operator)]


async def reader_lang(
    settings: SettingsDep,
    session: SessionDep,
    service: ServiceHeader = None,
    operator: OperatorHeader = None,
    lang: LangHeader = None,
    authorization: Annotated[str | None, Header()] = None,
) -> UiLang:
    """The language of a read anybody may make, the console's server included.

    For reference data the console shows next to its own (the universities on
    a chat's page). Anybody else is registered on first sight, as `UserDep` does.
    """
    if service is not None:
        return _service_operator(settings, service, operator, lang).lang
    user = await current_user(
        await current_identity(settings, authorization), session, settings
    )
    return user.ui_lang


ReaderLangDep = Annotated[UiLang, Depends(reader_lang)]


async def current_notifier(http: Request, settings: SettingsDep) -> Notifier:
    """Assemble a notifier from what the process was started with.

    The bot is put on `app.state` by the lifespan, which is also the reason for
    the default: a test builds the app without running it, and so does a
    session that never got a token. Both are "no bot", which a `Notifier`
    already answers for — but only if the reach happens somewhere that can
    decide it once, rather than in each route that happens to send a message.

    Per request, and cheap: two attribute reads and a cached `Settings`. It
    reads state fixed at startup but is not itself a singleton, and it is one
    of the few places that reach for `app.state`: see docs/architecture.md.
    """
    return Notifier(
        getattr(http.app.state, "bot", None),
        settings.public_base_url or None,
        owner_tg_id=settings.owner_tg_id,
    )


NotifierDep = Annotated[Notifier, Depends(current_notifier)]


async def current_handle(http: Request) -> BotHandle:
    """The bot's own handle, as one object per process.

    Built here rather than in the lifespan, and kept: what a handler needs is
    composed from what the process was started with, which is this module's
    job, and the lifespan does not run under the test client or under an app
    built by a script. One construction site means the path production takes
    is the path the tests take.

    Built on the first request rather than at import, because that is when the
    bot exists: the lifespan has already run by then, so a `None` cached here
    means the process really has no token.

    `async` like every other dependency here, and not only for symmetry: a
    plain `def` would be dispatched to a worker thread, and two first requests
    landing together would each build a handle and each ask Telegram.
    """
    handle = getattr(http.app.state, "bot_handle", None)
    if handle is None:
        handle = BotHandle(getattr(http.app.state, "bot", None))
        http.app.state.bot_handle = handle
    return handle


HandleDep = Annotated[BotHandle, Depends(current_handle)]
