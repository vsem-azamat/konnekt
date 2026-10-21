import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
    computed_field,
    field_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _find_env_file(start: Path | None = None) -> Path | None:
    """Walk up from this file looking for a .env, no higher than the project.

    Not a fixed number of parents: the checkout puts this module deeper than
    the container image does, and hard-coding the depth made it raise
    IndexError on import inside Docker. The walk stops at the directory that
    holds alembic.ini — `catalog/` in the checkout, `/app` in the image —
    because above it is supervisor-telegram's own .env, whose settings are not
    this service's.
    """
    here = (start or Path(__file__)).resolve()
    for directory in here.parents:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        if (directory / "alembic.ini").is_file():
            return None
    return None


ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    # One .env in catalog/, shared with compose.dev.yml, so the database
    # credentials cannot drift between the container and the application.
    # Found regardless of where the process was started from — and in
    # production there is no file at all, only the environment.
    model_config = SettingsConfigDict(
        # Only the one found above. A bare ".env" would be read from wherever
        # the process starts, the repository root included.
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    postgres_user: str = "students_cz"
    postgres_password: str = "students_cz"
    postgres_db: str = "students_cz"
    postgres_host: str = "127.0.0.1"
    # 5433 on the host: 5432 is usually taken by a local Postgres.
    postgres_port: int = 5433

    # Set this to override the assembled URL, e.g. when the API runs inside
    # compose and has to reach the database by service name.
    database_url: str | None = None
    db_echo: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # One JSON line a record for the log shipper; "text" for reading in a terminal.
    log_format: Literal["json", "text"] = "json"

    # One pool per process, and the Dockerfile pins `--workers 1`, so these are
    # the whole connection budget: at most `db_pool_size + db_max_overflow`
    # against Postgres. Raise them together with the worker count, never one
    # without looking at the other.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    # Postgres and anything in front of it will close an idle connection
    # eventually and say nothing. pool_pre_ping catches that on checkout at the
    # cost of a round trip; recycling retires connections before they get old
    # enough for it to matter.
    db_pool_recycle_seconds: int = 1800

    @computed_field
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Telegram ────────────────────────────────────────────────────────
    # The moderator bot's token in production. Used to send and to check
    # initData, never to receive: see docs/architecture.md.
    bot_token: str = ""
    # Told when a profile or a request appears, and nothing else. Unset — which
    # is how it runs everywhere but production — means no ping. A numeric
    # Telegram id and not a handle: the bot needs a chat it can open, and it
    # can only open one with somebody who has started the moderator bot.
    owner_tg_id: int | None = None
    # Who reads the catalog in the moderator console: the same Telegram ids as
    # supervisor's ADMIN_SUPER_ADMINS. See docs/architecture.md. NoDecode: the
    # deploy writes "1,2", which is not the JSON list pydantic would expect.
    admin_tg_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    # What supervisor's webapi shows when it asks for an operator it signed in
    # (the console in a browser has no initData). Shared by the two containers
    # alone, never sent by a browser. Unset turns that way in off. See
    # docs/architecture.md.
    service_token: SecretStr = SecretStr("")
    # The bearer token Prometheus presents, and the switch for the metrics
    # endpoint: unset, nothing answers. See core/metrics.py.
    observability_metrics_secret: SecretStr = SecretStr("")
    # Who a business writes to about advertising: a Telegram username. Unset
    # means the ads page offers no contact. See docs/architecture.md.
    ads_contact: str | None = None

    @field_validator("ads_contact", mode="before")
    @classmethod
    def _a_username_or_nobody(cls, value: object) -> object:
        """A username, forgiving a leading «@»; anything else refuses to start.

        A typo in a deploy variable should stop the deploy, not become a
        button that opens nothing.
        """
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("ADS_CONTACT must be a Telegram username")
        username = value.strip().removeprefix("@")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", username):
            raise ValueError("ADS_CONTACT must be a Telegram username, without a link")
        return username

    @field_validator("service_token", "observability_metrics_secret", mode="before")
    @classmethod
    def _strong_or_off(cls, value: object, info: ValidationInfo) -> object:
        """Spaces around it dropped, blank is off, and a short one refuses to start.

        A token pasted with a newline would otherwise never match, and a short
        one is a guess away from acting as an operator.
        """
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            return value
        raw = raw.strip()
        if raw and len(raw) < 32:
            name = str(info.field_name).upper()
            raise ValueError(f"{name} must be at least 32 characters, or unset")
        return SecretStr(raw)

    @field_validator("admin_tg_ids", mode="before")
    @classmethod
    def _comma_separated(cls, value: object) -> object:
        """ "1, 22" as the deploy writes it; empty is nobody; a typo refuses to start."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("owner_tg_id", mode="before")
    @classmethod
    def _blank_is_nobody(cls, value: object) -> object:
        """An unset variable reaches us as an empty string, not as absent.

        Compose writes `OWNER_TG_ID=` whether or not anybody set it, and an
        empty string is not an integer — so without this the API refuses to
        start in exactly the configuration that means "no ping".
        """
        return None if value == "" else value

    # The Mini App's HTTPS origin (APP_URL in production), which the bot's
    # buttons open. It is another host: the app's router proxies /api/v1/*
    # here, because Telegram only allows Mini App API calls from the app's
    # own origin.
    public_base_url: str = ""

    # How long an initData payload stays usable. Telegram mandates nothing here
    # and aiogram does not check it at all — the number is ours. A day is long
    # enough that a session does not expire mid-use, short enough that a leaked
    # payload is not a standing key.
    init_data_max_age_seconds: int = 86_400
    # Lets the API run without a bot token in local development. Never true in
    # anything reachable from the internet.
    allow_unsigned_init_data: bool = False

    # ── Behaviour ───────────────────────────────────────────────────────
    default_currency: str = "CZK"
    default_ui_lang: str = "ru"
    supported_ui_langs: tuple[str, ...] = ("ru", "cs", "en", "uk")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
