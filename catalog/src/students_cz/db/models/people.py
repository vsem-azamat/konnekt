"""Accounts and helper profiles.

There is no separate "teacher" table. Everyone is a :class:`User`; offering help
is a role you take on by having a :class:`HelperProfile`. The legacy schema had
``Users`` and ``Teachers`` as parallel tables joined on the Telegram id, which
made "a tutor who is also looking for a tutor" unrepresentable.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
    TSTZRANGE,
    ExcludeConstraint,
    Range,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from students_cz.db.base import Base, IdMixin, TimestampMixin
from students_cz.db.models.enums import (
    HIDE_NOTE_MAX,
    ContentLang,
    HideReason,
    PublishStatus,
    UiLang,
    WorkFormat,
    pg_enum,
)

if TYPE_CHECKING:
    from students_cz.db.models.catalog import Offer


class User(IdMixin, TimestampMixin, Base):
    """A Telegram account we have seen at least once."""

    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(String(512))

    # Seeded from Telegram's language_code on first launch, overridable in the
    # profile. Falls back to RU because that is what most of the audience picks.
    ui_lang: Mapped[UiLang] = mapped_column(
        pg_enum(UiLang, "ui_lang"), nullable=False, default=UiLang.RU, server_default="ru"
    )
    # Languages this person is comfortable communicating in. Used to filter the
    # catalog: a Ukrainian first-year usually cannot work with a Czech-only tutor.
    spoken_langs: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), nullable=False, server_default="{}"
    )

    city: Mapped[str | None] = mapped_column(String(96))
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), index=True
    )

    # Telegram Premium. Cheap to record and the only spending signal we get.
    is_premium: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # ── reachability ────────────────────────────────────────────────────
    # A bot may only write to someone who started it. Recording when that
    # happened is what separates "we have their id" from "we may message them".
    bot_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Flipped off when Telegram answers 403. Sending to a user who blocked the
    # bot is not an error to retry, it is an answer.
    bot_can_message: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Set when someone asks to stop hearing from us. Separate from
    # bot_can_message: one is their choice, the other is Telegram's report.
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # start_param from the Mini App deep link that brought them
    # (t.me/<bot>/<app>?startapp=<source>). None reaches the catalog yet: it is
    # not a named Mini App of the moderator bot. See docs/architecture.md.
    # First one wins — the question is where someone came from, not where they
    # most recently came from.
    source: Mapped[str | None] = mapped_column(String(64), index=True)

    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    helper: Mapped["HelperProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_users_spoken_langs", "spoken_langs", postgresql_using="gin"),
        # The audience query for any announcement: started the bot, has not
        # blocked it, has not opted out.
        Index(
            "ix_users_reachable",
            "bot_can_message",
            "unsubscribed_at",
            "bot_started_at",
        ),
    )


class HelperProfile(TimestampMixin, Base):
    """The "I can help" side of an account.

    Keyed by ``user_id`` rather than its own id: a user has at most one helper
    profile, and sharing the key removes a join from every catalog query.
    """

    __tablename__ = "helper_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    headline: Mapped[str | None] = mapped_column(String(160))
    about: Mapped[str | None] = mapped_column(Text)
    about_lang: Mapped[ContentLang] = mapped_column(
        pg_enum(ContentLang, "content_lang"),
        nullable=False,
        default=ContentLang.RU,
        server_default="ru",
    )
    # Exactly what the person typed into the single onboarding field, before we
    # extracted subjects and prices from it. Kept so the extractor can be
    # re-run and improved on real inputs.
    raw_intro: Mapped[str | None] = mapped_column(Text)

    status: Mapped[PublishStatus] = mapped_column(
        pg_enum(PublishStatus, "publish_status"),
        nullable=False,
        default=PublishStatus.DRAFT,
        server_default="draft",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When an operator looked at it in the console and kept or hid it; until
    # then a newly published profile waits on the console's «Новые анкеты».
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set with a ban and cleared with its lift; the owner reads both. The note
    # is the operator's own words for «Другое», and only for it.
    hidden_reason: Mapped[HideReason | None] = mapped_column(
        pg_enum(HideReason, "hide_reason")
    )
    hidden_note: Mapped[str | None] = mapped_column(String(HIDE_NOTE_MAX))

    work_format: Mapped[WorkFormat] = mapped_column(
        pg_enum(WorkFormat, "work_format"),
        nullable=False,
        default=WorkFormat.BOTH,
        server_default="both",
    )
    city: Mapped[str | None] = mapped_column(String(96))
    # Free text: "Dejvice, near the metro". Not worth geocoding at this size.
    place_note: Mapped[str | None] = mapped_column(String(240))

    # Denormalised counters. Recomputed by background jobs, never trusted as the
    # source of truth — they exist so list screens do not aggregate on every read.
    response_minutes_avg: Mapped[int | None] = mapped_column(Integer)
    deals_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rating: Mapped[float | None] = mapped_column(Numeric(2, 1))
    reviews_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    user: Mapped[User] = relationship(back_populates="helper")
    offers: Mapped[list["Offer"]] = relationship(
        back_populates="helper", cascade="all, delete-orphan"
    )
    availability: Mapped[list["AvailabilitySlot"]] = relationship(
        back_populates="helper", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_helper_profiles_status_published", "status", "published_at"),
        CheckConstraint(
            "rating IS NULL OR (rating >= 0 AND rating <= 5)",
            name="rating_range",
        ),
        # The reason is an operator's hide's and leaves with it; words only
        # for «Другое».
        CheckConstraint(
            "hidden_reason IS NULL OR status = 'banned'", name="reason_only_when_banned"
        ),
        CheckConstraint(
            "hidden_note IS NULL OR hidden_reason = 'other'", name="note_only_for_other"
        ),
    )


class AvailabilitySlot(IdMixin, Base):
    """A concrete window a helper is free in.

    Stored as a range so overlap checks are one operator. The exclusion
    constraint makes overlapping slots for the same helper impossible at the
    database level — this needs the ``btree_gist`` extension.
    """

    __tablename__ = "availability_slots"

    helper_id: Mapped[int] = mapped_column(
        ForeignKey("helper_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    # Range, not object: the bounds are read all over the availability code as
    # `.lower` and `.upper`, and an opaque annotation turned every one of them
    # into an attribute on `object` that no checker could vouch for.
    period: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, nullable=False)
    note: Mapped[str | None] = mapped_column(String(240))

    helper: Mapped[HelperProfile] = relationship(back_populates="availability")

    __table_args__ = (
        ExcludeConstraint(
            ("helper_id", "="),
            ("period", "&&"),
            name="availability_slots_no_overlap",
            using="gist",
        ),
        # tstzrange allows unbounded ends, and "free from now until the heat
        # death of the universe" is not a thing a person offers. Rejecting it
        # here also spares every reader a None check on the bounds.
        CheckConstraint(
            "NOT lower_inf(period) AND NOT upper_inf(period) AND NOT isempty(period)",
            name="period_is_bounded",
        ),
        Index("ix_availability_slots_period", "period", postgresql_using="gist"),
    )


class WeeklyAvailability(IdMixin, Base):
    """Recurring weekly availability, e.g. "Tue and Thu evenings".

    Kept separate from concrete slots because it answers a different question:
    slots say "free on 12 February", this says "generally reachable on Tuesdays".
    The search screen uses slots; the profile screen shows this.
    """

    __tablename__ = "weekly_availability"

    helper_id: Mapped[int] = mapped_column(
        ForeignKey("helper_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute",
            name="minute_range",
        ),
        Index("ix_weekly_availability_helper_weekday", "helper_id", "weekday"),
    )


class UserEducation(IdMixin, Base):
    """Where someone studies or studied.

    Drives the "on your faculty" ranking: a ČVUT FEL student trusts a ČVUT FEL
    tutor over an equally rated stranger. Flexible extras (year, programme,
    degree) live in ``attrs`` because they differ by country and school.
    """

    __tablename__ = "user_education"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    started_year: Mapped[int | None] = mapped_column(Integer)
    finished_year: Mapped[int | None] = mapped_column(Integer)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


__all__ = [
    "AvailabilitySlot",
    "HelperProfile",
    "User",
    "UserEducation",
    "WeeklyAvailability",
]
