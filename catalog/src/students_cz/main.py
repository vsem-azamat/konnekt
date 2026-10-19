"""One process: the API, and the bot it sends notifications through.

Keeping them together is not laziness — it is what makes the origin rule work.
Since 20 July 2026 Telegram only allows Mini App API calls from the app's own
origin, so the page and the API it talks to have to be the same host anyway.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from students_cz.api.v1 import router as api_router
from students_cz.api.v1.health import health_router
from students_cz.bot import build_bot
from students_cz.core.config import get_settings
from students_cz.db.session import dispose_engine
from students_cz.services import errors
from students_cz.services.embedding import get_embedder

log = logging.getLogger("students_cz")


class QuietHealthChecks(logging.Filter):
    """Drop the container healthcheck's requests from uvicorn's access log.

    It asks every 15 s; in one week 39,593 of 39,603 lines were it, and the
    rotated log kept three days of anything else.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        path = str(args[2]).split("?", 1)[0] if len(args) > 2 else ""
        return path != "/healthz"


def configure_logging(level: str) -> None:
    """Give this application's logger somewhere to write.

    Uvicorn configures its own loggers and nothing else, so without this the
    `students_cz` logger has no handler and falls back to Python's last-resort
    one — which only emits WARNING and above. Every `log.info` in the process
    went nowhere, including the one that says semantic search is off because
    the image carries no model.

    Records still propagate. Uvicorn does not configure the root logger, so
    there is nothing to duplicate against, and cutting propagation would also
    cut off whatever a deployment attaches there with `--log-config`.
    """
    log.setLevel(level)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietHealthChecks) for f in access.filters):
        access.addFilter(QuietHealthChecks())
    if any(isinstance(handler, logging.StreamHandler) for handler in log.handlers):
        # `create_app()` runs once per process, and once per test.
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    log.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.bot = None

    # Opened here rather than on the first search: half a second of loading a
    # 200 MB file belongs to the deploy, not to whoever types first. `None` when
    # the image carries no model, which is a supported way to run.
    get_embedder()

    # Built to send through and nothing else. The token is the moderator bot's
    # and so are its updates: no webhook, no command list, no menu button from
    # here. See docs/architecture.md.
    if settings.bot_token:
        app.state.bot = build_bot(settings)
    else:
        log.warning("BOT_TOKEN is unset — running API-only, nothing is sent")

    yield

    bot = app.state.bot
    if bot is not None:
        # Without this the aiohttp session behind the bot leaks on reload.
        await bot.session.close()
    await dispose_engine()


SERVICE_ERROR_STATUS: dict[type[errors.ServiceError], int] = {
    errors.NotFound: status.HTTP_404_NOT_FOUND,
    errors.Forbidden: status.HTTP_403_FORBIDDEN,
    errors.Conflict: status.HTTP_409_CONFLICT,
    errors.Invalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
    errors.BadRequest: status.HTTP_400_BAD_REQUEST,
}


def status_for(exc: BaseException) -> int:
    """The status a service error answers with, following the class hierarchy.

    Walked rather than looked up: an exact-type lookup turns a subclass of
    `Invalid` — or the base class raised by mistake — into a KeyError inside
    the error handler, which is a 500 with no body at all. An unmapped one is
    still a programming error, so it is logged rather than quietly given a
    plausible status.
    """
    for klass in type(exc).__mro__:
        mapped = SERVICE_ERROR_STATUS.get(klass)
        if mapped is not None:
            return mapped
    log.error("no status mapped for %s", type(exc).__name__)
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Students CZ",
        description="Student help catalog for the Czech Republic",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # The one place a service's vocabulary becomes a status code. Services
    # raise rules, not protocols, so that the bot can call the same code and
    # answer in words instead of in numbers.
    @app.exception_handler(errors.ServiceError)
    async def _service_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content={"detail": str(exc)})

    app.include_router(api_router)
    app.include_router(health_router)

    return app


app = create_app()
