"""Application configuration using Pydantic settings."""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Base for every settings group: an empty variable means "not set".

    Configuration travels to the host as environment variables, and a GitHub
    variable or secret that has never been given a value arrives as an empty
    string rather than not arriving at all. Without this, an unset
    ADMIN_REPORT_CHAT_ID does not fall back to its default — it fails to parse
    as an integer and takes the process down on boot, which is a long way from
    what "optional" is supposed to mean.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {key: value for key, value in data.items() if value != ""}


class DatabaseSettings(Settings):
    """Database configuration."""

    user: str = Field(..., description="Database user")
    password: str = Field(..., description="Database password")
    # "db" was the compose service name back when the database was part of the
    # stack. It is not, so the only useful default is the one a developer running
    # this on their own machine wants; production names the host explicitly and
    # the deploy refuses without it.
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    name: str = Field(..., description="Database name")

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def url(self) -> str:
        """Get async database URL."""
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)

    @property
    def sync_url(self) -> str:
        """Get sync database URL for Alembic."""
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)


class TelegramSettings(Settings):
    """Moderator bot configuration."""

    token: str = Field(..., description="Moderator bot token from BotFather")
    # A list in one variable, so `NoDecode` (see `AdminSettings.super_admins`). The
    # variable keeps its singular name: it held one token first, and renaming
    # it would mean renaming the deployed secret in the same release.
    retired_tokens: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="MODERATOR_BOT_RETIRED_TOKEN",
        description="Tokens of retired bots, comma-separated; each answers private messages with the new address",
    )

    model_config = SettingsConfigDict(
        env_prefix="MODERATOR_BOT_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("retired_tokens", mode="before")
    @classmethod
    def _split_retired(cls, value: Any) -> Any:
        # Whitespace too: a secret gets pasted one token per line, and a token holds none.
        return re.split(r"[\s,]+", value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _retired_once_each(self) -> TelegramSettings:
        """Two pollers on one token take turns receiving its updates.

        The current token pasted in among these is caught where the bots are
        built (`moved.build_moved_bots`), which can say so in the log.
        """
        self.retired_tokens = [token for token in dict.fromkeys(self.retired_tokens) if token]
        return self


class AdsBotSettings(Settings):
    """The ads contact desk, @konnekt_ads_bot: off without a token."""

    token: str = Field(default="", description="Ads bot token from BotFather; unset disables the desk")
    # Text, read where the bot is built: a mistyped id (a link, an @name) must
    # switch the desk off with a log line, not stop moderation from booting.
    group_id: str = Field(default="", description="The staff forum supergroup (-100…) the desk opens topics in")
    # The same variable as the catalog's ADS_CONTACT (docker-compose.yaml), so
    # the bot and the site's ads pages send people to one place. Text, for the
    # reason given above; `contact_username` is what is offered.
    contact: str = Field(default="", description="Telegram username advertisers and questions are sent to")
    name: str = Field(default="Konnekt · Связь", description="The desk's display name, written to Telegram at start")

    @property
    def contact_username(self) -> str | None:
        """The contact without its «@», or None when unset or not a username: no button to nowhere."""
        username = self.contact.strip().removeprefix("@")
        return username if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", username) else None

    model_config = SettingsConfigDict(
        env_prefix="ADS_BOT_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class AdminSettings(Settings):
    """Admin configuration."""

    # `NoDecode` is what makes the validator below reachable. Without it
    # pydantic-settings JSON-decodes a list field at the source, and a
    # comma-separated `ADMIN_SUPER_ADMINS` raises at startup before anything
    # gets a chance to split it — the same trap already documented on
    # `allowed_origins`, which quietly cost that setting its value. Here the
    # cost would be louder and worse: both processes refuse to boot the first
    # time a second administrator is added.
    super_admins: Annotated[list[int], NoDecode] = Field(..., description="List of super admin user IDs")
    report_chat_id: int | None = Field(default=None, description="Chat ID for reports")

    model_config = SettingsConfigDict(
        env_prefix="ADMIN_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("super_admins", mode="before")
    @classmethod
    def parse_admin_list(cls, v: Any) -> list[int]:
        """Parse comma-separated admin IDs.

        Comma-separated is the spelling the whole stack accepts: the catalog
        reads the same variable as ADMIN_TG_IDS and splits it on commas only.
        Brackets are tolerated here so a stray JSON array still boots this
        process, but do not deploy one. An empty list is refused: with no super
        admin there is no report chat, and the first /report would raise.
        """
        if isinstance(v, str):
            admins = [int(admin_id.strip()) for admin_id in v.strip().strip("[]").split(",") if admin_id.strip()]
        elif isinstance(v, list):
            admins = [int(admin_id) for admin_id in v]
        elif isinstance(v, int):
            admins = [v]
        else:
            raise ValueError("super_admins must be a comma-separated string, list, or integer")
        if not admins:
            raise ValueError("super_admins must name at least one administrator")
        return admins

    @property
    def default_report_chat_id(self) -> int:
        """Get default report chat ID (first super admin)."""
        return self.report_chat_id or self.super_admins[0]


class WebApiSettings(Settings):
    """Admin web UI / HTTP API configuration."""

    public_url: str = Field(
        default="",
        description="Public site URL. Also what the bot opens as a Mini App, so https or nothing.",
    )
    session_ttl_days: int = Field(default=30, description="Admin session TTL in days")
    session_cookie_name: str = Field(default="konnekt_admin_session")
    session_cookie_secure: bool = Field(
        default=True,
        description="Set Secure flag on session cookie. Disable only for local http:// dev.",
    )
    admin_url: str = Field(
        default="",
        description="Origin the console is opened at in a browser (not inside Telegram); the OpenID Connect redirect lives here.",
    )
    oidc_client_id: str = Field(
        default="", description="Client ID BotFather shows under Login Widget; unset disables the browser door"
    )
    oidc_client_secret: SecretStr = Field(default=SecretStr(""), description="Client Secret from the same place")
    # The catalog's console screens, for the console in a browser: it has no
    # initData, so webapi asks for the super admin it signed in. Over the
    # containers' own network, with the token both are started with; unset
    # leaves those screens to Telegram. See catalog/docs/architecture.md.
    catalog_url: str = Field(
        default="http://catalog-api:8000", description="The catalog's API on the containers' network"
    )
    catalog_service_token: SecretStr = Field(
        default=SecretStr(""), description="The catalog's SERVICE_TOKEN; unset turns the catalog's screens off here"
    )
    # Not "none". Lax is same-site, not same-origin: a sibling host under the
    # same domain still sends the cookie, which is why writes also check Origin
    # (app/webapi/origin_guard.py).
    session_cookie_samesite: Literal["lax", "strict"] = Field(default="lax", description="SameSite: lax|strict")

    @field_validator("catalog_service_token", mode="before")
    @classmethod
    def _strong_or_off(cls, value: object) -> object:
        """As the catalog reads its SERVICE_TOKEN: spaces dropped, blank is off,
        and a short one refuses to start (catalog/src/students_cz/core/config.py)."""
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            return value
        raw = raw.strip()
        if raw and len(raw) < 32:
            raise ValueError("WEBAPI_CATALOG_SERVICE_TOKEN must be at least 32 characters, or unset")
        return SecretStr(raw)

    @field_validator("session_cookie_samesite", mode="before")
    @classmethod
    def _samesite_lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    model_config = SettingsConfigDict(
        env_prefix="WEBAPI_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _the_console_has_a_host_of_its_own(self) -> WebApiSettings:
        """A console host equal to the Mini App's takes that site's traffic.

        One with a port or a path matches no request, so the console would be
        configured and unreachable. Refused at startup instead; the deploy
        refuses the same URLs (scripts/admin_host.sh). Local development may
        name a port on localhost.
        """
        if not self.admin_url:
            return self
        admin = urlsplit(self.admin_url)
        local = admin.hostname in {"localhost", "127.0.0.1"}
        if admin.scheme != ("http" if local else "https") or not admin.hostname:
            raise ValueError("admin_url must be an https URL")
        if (admin.port and not local) or admin.path.strip("/") or admin.query or admin.fragment:
            raise ValueError("admin_url must be a bare origin: no port, no path")
        if self.public_url and urlsplit(self.public_url).hostname == admin.hostname:
            raise ValueError("admin_url must not be the Mini App's host")
        return self

    @property
    def oidc_enabled(self) -> bool:
        """On when configured and off otherwise, like the other optional doors."""
        return bool(self.admin_url and self.oidc_client_id and self.oidc_client_secret.get_secret_value())

    @property
    def allowed_origins(self) -> list[str]:
        """Origins the API accepts, derived from where the UI is served.

        This used to be its own setting, documented as comma-separated — and it
        could never work that way: pydantic-settings JSON-decodes a list field
        at the source, before the validator that split on commas could run, so
        any real value raised at startup. Production therefore left it empty and
        fell back to the local development origin, which went unnoticed only
        because the UI and the API share a host and never trigger CORS.

        Origins derived from the URLs already configured cannot disagree with
        them: the Mini App's, and the admin site's when it has one. The trailing
        slash goes because browsers compare exactly.
        """
        return [url.rstrip("/") for url in (self.public_url, self.admin_url) if url]


class LoggingSettings(Settings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", description="Log format")
    file_path: str | None = Field(default="logs/bot.log", description="Log file path")
    max_bytes: int = Field(default=10485760, description="Max log file size in bytes (10MB)")
    backup_count: int = Field(default=5, description="Number of backup log files")

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ModerationSettings(Settings):
    """Heuristic moderation configuration.

    What remains after the LLM agent: the ad detector, which matches t.me links
    and @handles and records what it finds. No model, no escalation timeout —
    both belonged to a decision step that a person now makes.
    """

    ad_detector_enabled: bool = Field(
        default=True,
        description="Whether the heuristic ad detector (t.me / @username) records spam_pings",
    )
    ad_detector_whitelist: list[str] = Field(
        default_factory=list,
        description="Handles never flagged by the ad detector (e.g. ['@konnekt_channel', '@work_azamat'])",
    )
    ad_detector_snippet_chars: int = Field(
        default=200,
        description="Max chars of message text stored alongside each spam_ping",
    )

    model_config = SettingsConfigDict(
        env_prefix="MODERATION_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class CaptchaSettings(Settings):
    """The join captcha sent to applicants of chats that have it on."""

    answer_minutes: int = Field(
        default=15,
        ge=1,
        description="How long an applicant has to answer before the request is declined",
    )
    # Telegram lets the bot write to an applicant for five minutes after the
    # request, so a reminder any later would not arrive.
    remind_after_minutes: int = Field(
        default=4,
        ge=1,
        lt=5,
        description="When an applicant who has not answered gets one reminder",
    )

    model_config = SettingsConfigDict(
        env_prefix="CAPTCHA_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class McpSettings(Settings):
    """MCP server served by the bot process for external agent clients.

    The MCP endpoint is a second admin control plane alongside the cookie-authed
    web UI. The token is a shared secret presented as ``Authorization: Bearer``;
    it is not a user session, and it is also the switch — no token, no endpoint.

    It runs in the bot process rather than the web API because its moderation
    tools need the bot whose dispatcher answers the confirmation buttons they
    send — a proposal confirmed in a chat is answered by the identity that sent
    it, and that identity lives here.
    """

    token: str = Field(default="", description="Bearer token required by MCP clients; unset disables the endpoint")
    initiator_id: int = Field(
        default=0,
        description=(
            "Telegram ID of the admin this token acts as. Defaults to the first super "
            "admin, which is where confirmations go; set it only when the token should "
            "answer to someone else on that list."
        ),
    )

    # Not configurable. The compose port mapping hard-codes the container side,
    # so a configurable port would bind the app to one number while the mapping
    # forwarded another. The path is fixed for the same reason a URL is.
    path: str = "/api/mcp"
    host: str = "0.0.0.0"  # noqa: S104 — inside the container; the mapping is loopback-only
    port: int = 8788

    @property
    def active(self) -> bool:
        """True when there is a token to authenticate with.

        Failing closed keeps a misconfigured deploy from exposing admin tooling
        without authentication — and with no separate flag there is nothing that
        can claim to be enabled while the door has no lock.
        """
        return bool(self.token)

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ObservabilitySettings(Settings):
    """What Prometheus may read from this process.

    The secret is the bearer token the scrape job presents, and it is also the
    switch: unset, the endpoints answer nothing (app/core/metrics.py).
    """

    metrics_secret: SecretStr = Field(default=SecretStr(""), description="Bearer token for the metrics endpoints")

    # Not configurable, like the MCP plane's: the compose port mapping hard-codes
    # the container side, and the bot is the one process with no web front.
    metrics_host: ClassVar[str] = "0.0.0.0"  # noqa: S104 — inside the container; the mapping is loopback-only
    metrics_port: ClassVar[int] = 8789

    @field_validator("metrics_secret", mode="before")
    @classmethod
    def _strong_or_off(cls, value: object) -> object:
        """Spaces around it dropped, blank is off, and a short one refuses to start.

        A token pasted with a newline would never match, and a short one is a
        guess away from reading every counter.
        """
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            return value
        raw = raw.strip()
        if raw and len(raw) < 32:
            raise ValueError("OBSERVABILITY_METRICS_SECRET must be 32 characters or more, or unset")
        return raw

    model_config = SettingsConfigDict(
        env_prefix="OBSERVABILITY_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class AppSettings(Settings):
    """Main application settings."""

    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment name")
    timezone: str = Field(default="UTC", description="Application timezone")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    ads_bot: AdsBotSettings = Field(default_factory=AdsBotSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    moderation: ModerationSettings = Field(default_factory=ModerationSettings)
    captcha: CaptchaSettings = Field(default_factory=CaptchaSettings)
    webapi: WebApiSettings = Field(default_factory=WebApiSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
settings = AppSettings()
