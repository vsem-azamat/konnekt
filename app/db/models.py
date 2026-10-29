import datetime
import hashlib
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.enums import PendingActionStatus
from app.core.time import utc_now
from app.db.base import Base

# A generated primary key that is bigint on PostgreSQL. SQLite only auto-fills a
# primary key when its declared type is exactly INTEGER, so the variant keeps the
# test database working while production gets the wider column.
_AUTO_BIGINT = BigInteger().with_variant(Integer, "sqlite")


class Admin(Base):
    """Somebody trusted to moderate, in the chats named by ``admin_chats``.

    Being an administrator of a Telegram chat has nothing to do with this. That
    crown gets handed out so a name shows up in the member list; it is not a
    statement about who may ban people, and the bot has never treated it as one.

    Super administrators are not here. They live in ``ADMIN_SUPER_ADMINS``, in
    configuration, so that the set of people who can grant power cannot itself be
    changed by writing to the database.
    """

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    state: Mapped[bool] = mapped_column(Boolean, default=True)

    chats: Mapped[list["AdminChat"]] = relationship(
        back_populates="admin",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, id: int, state: bool = True) -> None:
        self.id = id
        self.state = state

    @property
    def is_active(self) -> bool:
        """Check if admin is active"""
        return self.state


class AdminChat(Base):
    """Which chats one administrator may act in.

    The scope is the whole point of the table. A flat list of administrators
    means whoever is trusted to keep order in one faculty chat can ban people in
    the other forty-four, which is not what anybody agreed to when they took the
    job.
    """

    __tablename__ = "admin_chats"

    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admins.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    admin: Mapped["Admin"] = relationship(back_populates="chats")


class Chat(Base):
    __tablename__ = "chats"

    # How far the bot's hand reaches here, in one column, so that a check for
    # "approved" is a check for active moderation and nothing else can mean it.
    #
    # Approved is a chat the bot moderates. Observed is one it sits in and
    # records but never speaks in: its owner's own bot is in charge there.
    # External is one the bot is not in at all, listed by its public link and
    # marked as somebody else's. Those three may be listed; discovered awaits a
    # decision and disabled was taken down.
    STATUS_DISCOVERED = "discovered"
    STATUS_APPROVED = "approved"
    STATUS_OBSERVED = "observed"
    STATUS_EXTERNAL = "external"
    STATUS_DISABLED = "disabled"
    VALID_RESOURCE_STATUSES = frozenset(
        {STATUS_DISCOVERED, STATUS_APPROVED, STATUS_OBSERVED, STATUS_EXTERNAL, STATUS_DISABLED}
    )
    LISTABLE_STATUSES = frozenset({STATUS_APPROVED, STATUS_OBSERVED, STATUS_EXTERNAL})

    # What the chat is about, for the catalogue's headings. A university's own
    # chats need none: their institution says it. "university" is for one the
    # catalog's taxonomy does not know yet, which has no code to say it.
    TOPICS = ("university", "subjects", "dorms", "work_it", "general")

    # What the bot does with a request to join. Only a chat that takes
    # requests has any: a public one with "approve new members" on in
    # Telegram, or a private one through the bot's own link, which asks for a
    # request in every mode but OPEN.
    #
    # OPEN approves every request to a public chat at once (a private one
    # admits through the bot's link without any), CAPTCHA asks the applicant first,
    # ADMINS leaves requests to the chat's admins. Anyone blacklisted is
    # declined whatever the mode.
    JOIN_OPEN = "open"
    JOIN_CAPTCHA = "captcha"
    JOIN_ADMINS = "admins"
    JOIN_MODES = (JOIN_OPEN, JOIN_CAPTCHA, JOIN_ADMINS)

    # What Telegram calls the chat, folded to what a reader tells apart: a
    # group they can talk in, or a channel they only read. A basic group and a
    # supergroup are both groups. Only an external listing is ever a channel:
    # the bot moderates groups, and a channel counted as ours would add
    # somebody else's subscribers to the reach we advertise. So a channel is
    # external or taken down, never approved, observed or awaiting a decision.
    KIND_GROUP = "group"
    KIND_CHANNEL = "channel"

    # A chat known only by its invite link has no id of Telegram's: the bot is
    # not in it, and only a member can learn the id. It gets one of ours from
    # below this line instead. Telegram's ids fit in 52 bits and a browser's
    # numbers are exact to 53, so the band between is no real chat's and still
    # survives JSON. Nothing asks the Bot API about an id in it (the loops skip
    # it, and a check keeps it external or taken down, never moderated); its
    # title, photo and count come from the link's public page (app/chats/previews.py).
    #
    # Should the bot be added there one day, Telegram's own row for the chat is
    # recorded beside this one, and the listing is moved onto it: parent, city,
    # topic and link are this row's to give, and the row is then removed.
    PREVIEW_ID_CEILING = -(2**52)

    __table_args__ = (
        sa.CheckConstraint(
            "resource_status IN ('discovered', 'approved', 'observed', 'external', 'disabled')",
            name="ck_chats_resource_status",
        ),
        sa.CheckConstraint(
            "topic IN ('university', 'subjects', 'dorms', 'work_it', 'general')",
            name="ck_chats_topic",
        ),
        sa.CheckConstraint("join_mode IN ('open', 'captcha', 'admins')", name="ck_chats_join_mode"),
        sa.CheckConstraint("kind IN ('group', 'channel')", name="ck_chats_kind"),
        sa.CheckConstraint(
            "kind = 'group' OR resource_status IN ('external', 'disabled')",
            name="ck_chats_channel_external",
        ),
        sa.CheckConstraint(
            f"id > {PREVIEW_ID_CEILING} OR resource_status IN ('external', 'disabled')",
            name="ck_chats_preview_external",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_status: Mapped[str] = mapped_column(String, default=STATUS_DISCOVERED, nullable=False)
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16), default=KIND_GROUP, server_default=KIND_GROUP)
    welcome_message: Mapped[str | None] = mapped_column(String, nullable=True)
    time_delete: Mapped[int] = mapped_column(Integer, default=60)
    is_welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # ADMINS until somebody chooses: the bot decides nobody's request on its own.
    join_mode: Mapped[str] = mapped_column(String(16), default=JOIN_ADMINS, server_default=JOIN_ADMINS)
    # Telegram's "approve new members", as getChat last said; None until asked.
    # Only a public chat's means anything: a private one takes requests by link.
    join_by_request: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The switch join_mode replaced, kept only so the previous release runs
    # beside this one during a deploy. Read by nothing; dropped by the next migration.
    _legacy_captcha: Mapped[bool] = mapped_column(
        "is_captcha_enabled", Boolean, default=False, server_default=sa.false()
    )

    # ADMINS given by the migration only for want of a link, to be settled by
    # the chat's first getChat answer. Any mode set afterwards is a choice.
    join_mode_guessed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())

    @validates("join_mode")
    def _keep_legacy_captcha(self, _key: str, mode: str) -> str:
        # Kept true to the mode, so a release rolled back to reads what was set.
        self._legacy_captcha = mode == self.JOIN_CAPTCHA
        self.join_mode_guessed = False
        return mode

    # On by default: a quiet chat otherwise reads as a membership log, dozens of
    # "joined"/"left" notices with the occasional real message lost among them.
    is_service_cleanup_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa.true())
    # With the captcha on, where it is asked: off, in a private message while
    # the request waits; on, in the chat itself, the applicant let in muted
    # (app/captcha/in_chat.py). Read when a request arrives.
    captcha_in_chat: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())
    parent_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("chats.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    relation_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    # Where a stranger can join, and by its presence the decision to let them.
    #
    # There is no accompanying `is_listed` flag on purpose. A flag beside a link
    # can disagree with it, and the disagreement is only ever discovered the way
    # all such disagreements are: a chat that was meant to be private turns out
    # to have been on a public page for a month. A chat is in the catalogue when
    # it is approved and this is set; taking it down means clearing it.
    #
    # Whose link it is depends on the chat. A username's is `t.me/<username>`.
    # Without one, once the chat is listed the bot owns the value: it keeps a
    # link of its own working and replaces it when Telegram says it is dead
    # (app/chats/invite_links.py). Listing stays a person's decision either way.
    public_link: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The university in the catalog's taxonomy, by its code ("cvut"), so
    # the app can put a student's own university first. Set on the chat at the
    # top; the chats under it carry it through their parent.
    institution_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The city the chat is for, named as the catalog's taxonomy names it
    # ("Praha"), so a student's university matches it. None is all of Czechia,
    # not "unknown": such a chat shows under every city. The chats under one
    # are in its city unless they name their own.
    city: Mapped[str | None] = mapped_column(String(96), nullable=True)
    # One of TOPICS, or None: a university's chat, or one nobody filed yet.
    topic: Mapped[str | None] = mapped_column(String(16), nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # What getChat last said about the chat, written only by app/chats/profile.py;
    # None until asked. No update announces a change to any of these, so they
    # are as fresh as last_synced_at.
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Telegram's own type: "group" and "supergroup" are both KIND_GROUP to a reader.
    chat_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    slow_mode_delay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What members may do unless an admin says otherwise, under Telegram's names.
    permissions: Mapped[dict[str, bool] | None] = mapped_column(JSON, nullable=True)
    has_protected_content: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_hidden_members: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_aggressive_anti_spam_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    message_auto_delete_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # When Telegram last told the bot it does not know this chat, or None while
    # it answers. The hourly loop asks such a chat once a day instead.
    bot_absent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # The supergroup this group became, as Telegram said when asked about it;
    # None while it is still itself. The old group is closed for good, so the
    # hourly loop stops asking it. The row stays, disabled, with its history;
    # its settings, moderators and listing move to the new id's row.
    migrated_to_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)
    modified_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    parent: Mapped["Chat | None"] = relationship(
        "Chat",
        remote_side="Chat.id",
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list["Chat"]] = relationship(
        "Chat",
        back_populates="parent",
        cascade="save-update, merge",
    )

    def __init__(
        self,
        id: int,
        title: str | None = None,
        resource_status: str = STATUS_DISCOVERED,
        is_forum: bool = False,
        kind: str = KIND_GROUP,
        welcome_message: str | None = None,
        time_delete: int = 60,
        is_welcome_enabled: bool = False,
        join_mode: str = JOIN_ADMINS,
        is_service_cleanup_enabled: bool = True,
        captcha_in_chat: bool = False,
        parent_chat_id: int | None = None,
        relation_notes: str | None = None,
        public_link: str | None = None,
        institution_code: str | None = None,
        city: str | None = None,
        topic: str | None = None,
    ) -> None:
        self.id = id
        self.title = title
        self.set_resource_status(resource_status)
        self.is_forum = is_forum
        self.kind = kind
        self.welcome_message = welcome_message
        self.time_delete = time_delete
        self.is_welcome_enabled = is_welcome_enabled
        self.join_mode = join_mode
        self.is_service_cleanup_enabled = is_service_cleanup_enabled
        self.captcha_in_chat = captcha_in_chat
        self.parent_chat_id = parent_chat_id
        self.relation_notes = relation_notes
        self.public_link = public_link
        self.institution_code = institution_code
        self.city = city
        self.topic = topic

    @property
    def is_captcha_enabled(self) -> bool:
        """Whether requests to join get the captcha; read-only, the mode is what is set."""
        return self.join_mode == self.JOIN_CAPTCHA

    def set_resource_status(self, status: str) -> None:
        """Set whether the bot may actively operate in this chat."""
        if status not in self.VALID_RESOURCE_STATUSES:
            raise ValueError(f"Unknown chat resource status: {status}")
        self.resource_status = status

    @property
    def is_approved(self) -> bool:
        return self.resource_status == self.STATUS_APPROVED

    @classmethod
    def preview_id_for(cls, invite_hash: str) -> int:
        """Our id for a chat known by this invite link: the same link always gives the same id."""
        digest = int.from_bytes(hashlib.sha256(invite_hash.encode()).digest()[:8], "big")
        return cls.PREVIEW_ID_CEILING - 1 - digest % 2**50

    @property
    def is_preview_only(self) -> bool:
        """Known only by its invite link's public page, and never to be asked through the Bot API."""
        return self.id <= self.PREVIEW_ID_CEILING


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # As Telegram last said; it often leaves the language out, and then the last one stays.
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_premium: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verify: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)
    modified_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    def __init__(
        self,
        id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        verify: bool = True,
        blocked: bool = False,
    ) -> None:
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.verify = verify
        self.blocked = blocked

    def block(self) -> None:
        """Block user (add to blacklist)"""
        self.blocked = True

    def unblock(self) -> None:
        """Unblock user (remove from blacklist)"""
        self.blocked = False

    @property
    def is_blocked(self) -> bool:
        """Check if user is blocked"""
        return self.blocked

    @property
    def display_name(self) -> str:
        """Get user's display name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.first_name:
            return self.first_name
        if self.username:
            return f"@{self.username}"
        return f"User {self.id}"


class ChatLink(Base):
    __tablename__ = "chat_links"

    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True)
    text: Mapped[str] = mapped_column(String, unique=True)
    link: Mapped[str] = mapped_column(String, unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    def __init__(self, text: str, link: str, priority: int = 0) -> None:
        self.text = text
        self.link = link
        self.priority = priority


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # One row per message: a redelivered update used to be a second one.
        Index("uq_messages_chat_message", "chat_id", "message_id", unique=True),
        # The public catalogue counts recent activity by time.
        Index("ix_messages_timestamp", "timestamp"),
        # The first-message spam check looks a text up among labelled spam. A
        # hash, because a btree refuses texts past ~2.7 kB, and partial, because
        # the labelled rows are the only ones it asks about.
        Index(
            "ix_messages_spam_text",
            "message",
            postgresql_using="hash",
            postgresql_where=sa.text("spam"),
            sqlite_where=sa.text("spam"),
        ),
    )

    # Wider than a plain serial: this table grows with every message the bot
    # sees, and the production database has held it as a bigint all along.
    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    message_info: Mapped[dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)
    spam: Mapped[bool] = mapped_column(Boolean, default=False)

    def __init__(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        message: str | None = None,
        message_info: dict[str, Any] | None = None,
        spam: bool = False,
    ) -> None:
        self.chat_id = chat_id
        self.user_id = user_id
        self.message_id = message_id
        self.message = message
        self.message_info = message_info or {}
        self.spam = spam


class PendingAction(Base):
    """A destructive action proposed from outside, awaiting an admin's press.

    ``origin`` and ``initiator_id`` exist because a ban is an attributable act.
    The MCP token identifies a runtime rather than a person, so the admin it
    maps to is recorded here and carried into the decision log — otherwise the
    audit trail says only that "the agent" banned someone.

    ``params`` holds the arguments the action needs on execution (mute
    duration, whether to revoke messages), which have nowhere to live between
    proposal and confirmation otherwise.
    """

    __tablename__ = "pending_actions"
    __table_args__ = (
        Index("ix_pending_actions_status_expires_at", "status", "expires_at"),
        # The columns are text, so the enums are re-stated here: this is where a
        # value that skipped the type system would otherwise land.
        sa.CheckConstraint("action IN ('ban', 'blacklist')", name="ck_pending_actions_action"),
        sa.CheckConstraint("origin IN ('mcp')", name="ck_pending_actions_origin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin: Mapped[str] = mapped_column(String(16))
    initiator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(32))
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    target_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=PendingActionStatus.PENDING)
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(
        self,
        origin: str,
        initiator_id: int,
        action: str,
        target_user_id: int,
        expires_at: datetime.datetime,
        chat_id: int | None = None,
        params: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        self.origin = origin
        self.initiator_id = initiator_id
        self.action = action
        self.target_user_id = target_user_id
        self.expires_at = expires_at
        self.chat_id = chat_id
        self.params = params or {}
        self.reason = reason


class JoinCheck(Base):
    """A join request waiting for its applicant to pass the Mini App check.

    Stored rather than carried in the Mini App's URL because the two halves run
    in different processes: the request arrives in the bot, the check is
    answered by the web API. It also binds the query to one applicant — without
    that, anyone holding a query id could pass the check on someone else's
    behalf, which is exactly the bot-farm case a check exists to stop.
    """

    __tablename__ = "join_checks"

    query_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    passed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(self, query_id: str, chat_id: int, user_id: int, expires_at: datetime.datetime) -> None:
        self.query_id = query_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.expires_at = expires_at


class CatalogPass(Base):
    """A person who tapped to join one of our chats in the Mini App's catalog.

    Telegram signed that tap, so the account is somebody's own client: the
    proof the captcha asks for. It waits for the join request that follows and
    is spent by it (`app/captcha/service.py`). One row per person and chat, so
    tapping again renews it instead of piling up.
    """

    __tablename__ = "catalog_passes"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(self, user_id: int, chat_id: int, expires_at: datetime.datetime) -> None:
        self.user_id = user_id
        self.chat_id = chat_id
        self.expires_at = expires_at


class JoinCaptcha(Base):
    """One request to join and the emoji its applicant was asked to tap.

    A row per request, whether the captcha went out or not: the wave check
    counts them, and the expiry sweep finds the ones nobody answered, including
    those left open by a restart.
    """

    __tablename__ = "join_captchas"
    __table_args__ = (Index("ix_join_captchas_chat_id_created_at", "chat_id", "created_at"),)

    # Sent, waiting for a tap.
    STATUS_PENDING = "pending"
    # Arrived during a wave: not written to, left in Telegram for the admins.
    STATUS_HELD = "held"
    STATUS_PASSED = "passed"
    # Approved without a captcha: passed one in another chat lately. Never
    # itself a reason to trust, or trust would renew without anybody tapping.
    STATUS_TRUSTED = "trusted"
    # Approved without a captcha: tapped to join from the Mini App's catalog,
    # where Telegram signed who they are. Like trusted, never a reason to trust.
    STATUS_CATALOG = "catalog"
    # Out of tries.
    STATUS_FAILED = "failed"
    # Out of time.
    STATUS_EXPIRED = "expired"
    # Turned away with the wave it came in.
    STATUS_DECLINED = "declined"
    # Telegram refused the private message, so the request is the admins' again.
    STATUS_UNDELIVERED = "undelivered"
    # Closed by someone else (an admin, another bot) before the applicant answered.
    STATUS_GONE = "gone"

    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    # Where the captcha goes. Telegram allows writing there for five minutes.
    user_chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), index=True)
    answer: Mapped[str] = mapped_column(String(16))
    options: Mapped[list[str]] = mapped_column(JSON)
    attempts_left: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wave_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # Set before the reminder goes out, so it goes out once even if Telegram refuses it.
    reminded_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # Asked in the chat: let in muted, named in a message there (the card),
    # asked in a private message once they open the bot from it.
    in_chat: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())
    card_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # When the card that first named them went up; None until one has.
    announced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # When the private message went out, for the reminder.
    asked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(
        self,
        *,
        chat_id: int,
        user_id: int,
        user_chat_id: int,
        status: str,
        answer: str,
        options: list[str],
        attempts_left: int,
        created_at: datetime.datetime,
        expires_at: datetime.datetime,
        wave_id: int | None = None,
        in_chat: bool = False,
    ) -> None:
        self.chat_id = chat_id
        self.user_id = user_id
        self.user_chat_id = user_chat_id
        self.status = status
        self.answer = answer
        self.options = options
        self.attempts_left = attempts_left
        self.created_at = created_at
        self.expires_at = expires_at
        self.wave_id = wave_id
        self.in_chat = in_chat


class JoinWave(Base):
    """A burst of join requests to one chat, and what an admin decided about it."""

    __tablename__ = "join_waves"

    DECISION_DECLINE = "decline"
    DECISION_RESUME = "resume"
    DECISION_LEAVE = "leave"

    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    # The last moment requests came faster than the threshold; the pause ends
    # a quiet spell after it.
    last_surge_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    alert_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(self, *, chat_id: int, started_at: datetime.datetime) -> None:
        self.chat_id = chat_id
        self.started_at = started_at
        self.last_surge_at = started_at


class ChatAvatar(Base):
    """A chat's photo as bytes we serve ourselves, one row per chat.

    A Telegram file id cannot be shown to a browser, and the only URL Telegram
    gives for its file carries the bot token, so the picture is downloaded once
    and kept. It lives in the database rather than on a volume because the bot
    writes it and the web API reads it, in different containers: the database is
    the one place both already reach, a backup already covers, and a few hundred
    160 px JPEGs are well under a megabyte.

    ``unique_id`` is Telegram's ``file_unique_id`` for the photo: it changes when
    the chat changes its photo and not otherwise, so it is both the test for "do
    we need to fetch again" and the address the picture is served at, which is
    why the address can be cached forever.
    """

    __tablename__ = "chat_avatars"

    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True)
    unique_id: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(32), default="image/jpeg")
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(self, chat_id: int, unique_id: str, content: bytes, content_type: str = "image/jpeg") -> None:
        self.chat_id = chat_id
        self.unique_id = unique_id
        self.content = content
        self.content_type = content_type


class WelcomeGreeting(Base):
    """A chat greeting that is up, and when it is to go: one row per join it greets.

    The greeting lives in the bot's memory while joins add names to it, and a
    restart forgets it. This is what deletes it on time anyway: the captcha
    sweep removes every greeting whose latest row is due (`app/chats/welcome.py`).
    A join added to a greeting is a row of its own rather than an update, so
    two joins at once never write the same row.
    """

    __tablename__ = "welcome_greetings"
    __table_args__ = (Index("ix_welcome_greetings_chat_id_message_id", "chat_id", "message_id"),)

    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    delete_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(self, chat_id: int, message_id: int, delete_at: datetime.datetime) -> None:
        self.chat_id = chat_id
        self.message_id = message_id
        self.delete_at = delete_at


class UserPhoto(Base):
    """A person's Telegram photo as the console shows it, one row per person shown.

    Kept in the database for the reasons ``ChatAvatar`` gives. It is fetched the
    first time the console shows someone rather than for everybody ahead of time:
    the console shows a few dozen people, the bot has seen thousands.

    A row without ``content`` is an answer as well: Telegram showed the bot no
    photo, because there is none or the person's privacy settings hide it.
    Asking again on every page load would only find the same.
    """

    __tablename__ = "user_photos"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    unique_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str] = mapped_column(String(32), default="image/jpeg")
    fetched_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(
        self,
        user_id: int,
        unique_id: str | None,
        content: bytes | None,
        fetched_at: datetime.datetime | None = None,
        content_type: str = "image/jpeg",
    ) -> None:
        self.user_id = user_id
        self.unique_id = unique_id
        self.content = content
        self.content_type = content_type
        self.fetched_at = fetched_at or utc_now()


class ChatMemberSnapshot(Base):
    """Periodic member-count observations for managed chats.

    Populated by the webapi's lifespan snapshot loop. Deltas on the home
    dashboard are computed by comparing the most recent snapshot against
    an older baseline (typically 24h / 7d back).
    """

    __tablename__ = "chat_member_snapshots"
    __table_args__ = (Index("ix_chat_member_snapshots_chat_id_captured_at", "chat_id", "captured_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    member_count: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now, index=True)

    def __init__(self, chat_id: int, member_count: int, captured_at: datetime.datetime | None = None) -> None:
        self.chat_id = chat_id
        self.member_count = member_count
        if captured_at is not None:
            self.captured_at = captured_at


class ChatMember(Base):
    """What one person is in one chat now, as Telegram last said: member, restricted, left, kicked, administrator or creator.

    Written only by `app/chats/members.py`, from membership updates and, for
    administrators, from the daily check. Only the current state: a ban or a
    mute is in moderation_events, and comings and goings are not kept.
    `rights` is every true-or-false field of Telegram's member object (an
    administrator's rights, a restricted member's permissions).
    """

    __tablename__ = "chat_members"
    __table_args__ = (Index("ix_chat_members_user_id", "user_id"),)

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(String(16))
    rights: Mapped[dict[str, bool]] = mapped_column(JSON)
    # Until when a restriction or a ban holds (for a member, a paid subscription);
    # None is for good, or none. Telegram sends nothing when it runs out.
    until_date: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    changed_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    known_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    # Telegram's number for the update that set the state, to order two from the
    # same second; None when the daily check set it.
    update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ChatBotRights(Base):
    """What the moderator bot is in one chat now, as Telegram last said.

    Written only by `app/chats/bot_rights.py`, from the bot's own membership
    updates and from the daily check. `rights` is every true-or-false field of
    Telegram's member object, under Telegram's names. `changed_at` is when
    the status or a right last changed; `known_at` when it was last confirmed,
    so an update older than that changes nothing.
    """

    __tablename__ = "chat_bot_rights"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(String(16))
    rights: Mapped[dict[str, bool]] = mapped_column(JSON)
    changed_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    known_at: Mapped[datetime.datetime] = mapped_column(DateTime)


class ChatBotRightsChange(Base):
    """One change of the bot's status or rights in a chat, kept for good.

    The state it changed to; the state before is the previous row. `changed_by`
    is who Telegram says made it, None when the daily check found it.
    """

    __tablename__ = "chat_bot_rights_changes"
    __table_args__ = (Index("ix_chat_bot_rights_changes_chat_id_changed_at", "chat_id", "changed_at"),)

    id: Mapped[int] = mapped_column(_AUTO_BIGINT, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    rights: Mapped[dict[str, bool]] = mapped_column(JSON)
    changed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    changed_at: Mapped[datetime.datetime] = mapped_column(DateTime)


class SpamPing(Base):
    """A single ad-detection event.

    Persisted by the moderator middleware whenever a message contains
    t.me / telegram.me / @username patterns that are not ours or a
    classmate's (app/moderation/ad_detector_service.py). Powers the home "Spam pings" tile and the per-chat feed
    on /chats/:id.
    """

    __tablename__ = "spam_pings"
    __table_args__ = (
        Index("ix_spam_pings_chat_id_detected_at", "chat_id", "detected_at"),
        Index("ix_spam_pings_detected_at", "detected_at"),
        # The console's queue: what waits, newest first, a page at a time.
        Index(
            "ix_spam_pings_unreviewed",
            "detected_at",
            "id",
            postgresql_where=sa.text("verdict IS NULL"),
            sqlite_where=sa.text("verdict IS NULL"),
        ),
        sa.CheckConstraint("verdict IN ('done', 'not_ad', 'ad')", name="ck_spam_pings_verdict"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    matches: Mapped[list[str]] = mapped_column(JSON)
    snippet: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)
    # A SpamVerdict from the console; none while the hit waits in the queue.
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __init__(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        kind: str,
        matches: list[str],
        snippet: str | None = None,
        detected_at: datetime.datetime | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.user_id = user_id
        self.message_id = message_id
        self.kind = kind
        self.matches = matches
        self.snippet = snippet
        if detected_at is not None:
            self.detected_at = detected_at


class ModerationEvent(Base):
    """One thing a moderator did to one member.

    The bot used to keep no record of its own commands: a ``/ban`` typed in a
    chat left a Telegram-side restriction and nothing else, so "what has this
    user been through here" could only be answered from what the *user* did.
    A row goes in after the action succeeds, never before — a refused ban is
    not a ban.

    ``actor_id`` is a person even when the request came from elsewhere; see
    :class:`~app.core.enums.ModerationEventSource`. ``chat_id`` is null for the
    blacklist, which spans every chat rather than naming one.
    """

    __tablename__ = "moderation_events"
    __table_args__ = (
        Index("ix_moderation_events_target_user_id_created_at", "target_user_id", "created_at"),
        # Text columns, so the enums are restated where a value that skipped the
        # type system would land — the same guard pending_actions carries.
        sa.CheckConstraint(
            "action IN ('ban', 'unban', 'kick', 'mute', 'unmute', 'blacklist', 'unblacklist', "
            "'grant', 'revoke', 'delete', 'purge', 'pin', 'unpin')",
            name="ck_moderation_events_action",
        ),
        sa.CheckConstraint("source IN ('command', 'mcp', 'console')", name="ck_moderation_events_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(
        self,
        action: str,
        source: str,
        actor_id: int,
        target_user_id: int,
        chat_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.action = action
        self.source = source
        self.actor_id = actor_id
        self.target_user_id = target_user_id
        self.chat_id = chat_id
        self.detail = detail


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __init__(
        self,
        session_id: str,
        user_id: int,
        *,
        created_at: datetime.datetime,
        last_seen_at: datetime.datetime,
        expires_at: datetime.datetime,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = created_at
        self.last_seen_at = last_seen_at
        self.expires_at = expires_at
        self.user_agent = user_agent
        self.ip = ip


class AdsTopic(Base):
    """The forum topic of the staff group that holds one person's conversation with the ads bot.

    Stored so that a restart does not open a second topic for somebody already
    talking to staff, and keyed by the group as well, so that moving the desk
    to another group opens fresh topics there instead of writing into threads
    of a group the bot has left.
    """

    __tablename__ = "ads_topics"
    __table_args__ = (UniqueConstraint("group_id", "thread_id", name="uq_ads_topics_group_id_thread_id"),)

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utc_now)

    def __init__(self, group_id: int, user_id: int, thread_id: int) -> None:
        self.group_id = group_id
        self.user_id = user_id
        self.thread_id = thread_id


class AudienceMember(Base):
    """Somebody who has used one of our bots or the Mini App at least once.

    Kept apart from ``users``, which also holds everybody who ever wrote in a
    moderated group: being in a group the bot watches is not using Konnekt,
    and a bot cannot write to someone who has not opened a chat with it.
    Only what Telegram itself tells us about the person is stored, never what
    they wrote. ``opted_out_at`` is for announcements that do not exist yet:
    whoever sets it must never hear from them.
    """

    __tablename__ = "audience_members"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false())
    # The start or startapp payload that first brought them; later ones say less.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime, index=True)
    opted_out_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)


class AudienceTouch(Base):
    """When one person first and last used one touchpoint, and how many times."""

    __tablename__ = "audience_touches"
    __table_args__ = (
        sa.CheckConstraint(
            "touchpoint IN ('main_bot', 'contact_bot', 'mini_app', 'moved_bot')", name="ck_audience_touches_touchpoint"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("audience_members.user_id", ondelete="CASCADE"), primary_key=True
    )
    touchpoint: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    last_at: Mapped[datetime.datetime] = mapped_column(DateTime)
    count: Mapped[int] = mapped_column(Integer, default=1)


class AudienceReach(Base):
    """Whether one bot may write to one person.

    A bot may write to whoever has opened a chat with it (``started_at``) and
    has not blocked it since (``blocked_at``). Telegram reports a block as a
    membership change of the private chat, or as a 403 on the next send.
    ``known_at`` is the time of the latest event that set this state: events
    arrive late and are replayed, and one older than that changes nothing.
    """

    __tablename__ = "audience_reach"
    __table_args__ = (sa.CheckConstraint("bot IN ('main_bot', 'contact_bot')", name="ck_audience_reach_bot"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("audience_members.user_id", ondelete="CASCADE"), primary_key=True
    )
    bot: Mapped[str] = mapped_column(String(16), primary_key=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    blocked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    known_at: Mapped[datetime.datetime] = mapped_column(DateTime)
