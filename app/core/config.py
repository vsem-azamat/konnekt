"""Application configuration using Pydantic settings."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
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
    retired_token: str = Field(
        default="",
        description="Token of the retired catalog bot (@student_cz_bot); set, it answers with the new address",
    )

    model_config = SettingsConfigDict(
        env_prefix="MODERATOR_BOT_",
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
    # Not "none": SameSite is the only defence the console's mutations have
    # against a request another site makes with the admin's cookie.
    session_cookie_samesite: Literal["lax", "strict"] = Field(default="lax", description="SameSite: lax|strict")

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

    @property
    def allowed_origins(self) -> list[str]:
        """Origins the API accepts, derived from where the UI is served.

        This used to be its own setting, documented as comma-separated — and it
        could never work that way: pydantic-settings JSON-decodes a list field
        at the source, before the validator that split on commas could run, so
        any real value raised at startup. Production therefore left it empty and
        fell back to the local development origin, which went unnoticed only
        because the UI and the API share a host and never trigger CORS.

        One origin, derived from the URL already configured, cannot disagree
        with itself. The trailing slash goes because browsers compare exactly.
        """
        return [self.public_url.rstrip("/")] if self.public_url else []


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


class AppSettings(Settings):
    """Main application settings."""

    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment name")
    timezone: str = Field(default="UTC", description="Application timezone")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    moderation: ModerationSettings = Field(default_factory=ModerationSettings)
    webapi: WebApiSettings = Field(default_factory=WebApiSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Global settings instance
settings = AppSettings()
