"""Student requests — the inverse of the catalog.

A directory only works once it is full. Until then the useful direction is the
other one: a student posts "calculus, ČVUT, exam on 14 February" and helpers
answer. This is also the honest way to discover demand the catalog cannot serve
yet.
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from students_cz.db.base import Base, IdMixin, TimestampMixin
from students_cz.db.models.enums import (
    ContentLang,
    PriceUnit,
    RequestStatus,
    ResponseStatus,
    WorkFormat,
    pg_enum,
)


class HelpRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "help_requests"

    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # What the person actually typed. The structured columns below are our
    # interpretation of it; this stays as written so a better parser can be
    # replayed over real inputs.
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[ContentLang] = mapped_column(
        pg_enum(ContentLang, "content_lang"),
        nullable=False,
        default=ContentLang.RU,
        server_default="ru",
    )

    service_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_types.id", ondelete="SET NULL")
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL")
    )
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL")
    )

    deadline_on: Mapped[date | None] = mapped_column(Date)
    budget_max: Mapped[float | None] = mapped_column(Numeric(10, 2))
    budget_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="CZK"
    )
    budget_unit: Mapped[PriceUnit | None] = mapped_column(
        pg_enum(PriceUnit, "price_unit")
    )

    langs: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), nullable=False, server_default="{}"
    )
    work_format: Mapped[WorkFormat] = mapped_column(
        pg_enum(WorkFormat, "work_format"),
        nullable=False,
        default=WorkFormat.BOTH,
        server_default="both",
    )
    city: Mapped[str | None] = mapped_column(String(96))

    status: Mapped[RequestStatus] = mapped_column(
        pg_enum(RequestStatus, "request_status"),
        nullable=False,
        default=RequestStatus.DRAFT,
        server_default="draft",
    )
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Requests rot fast — an exam on 14 February is worthless on the 15th.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the author closed it. A request past its deadline closes without
    # anybody doing it, and that moment is `expires_at`.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    responses: Mapped[list["RequestResponse"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_help_requests_open", "status", "expires_at"),
        Index(
            "ix_help_requests_match", "subject_id", "institution_id", "service_type_id"
        ),
        Index("ix_help_requests_langs", "langs", postgresql_using="gin"),
    )


class RequestResponse(IdMixin, TimestampMixin, Base):
    __tablename__ = "request_responses"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("help_requests.id", ondelete="CASCADE"), nullable=False
    )
    helper_id: Mapped[int] = mapped_column(
        ForeignKey("helper_profiles.user_id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    price_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="CZK"
    )
    # Nullable, and separately from the amount: "500" alone is ambiguous
    # between an hour and the whole job, and an offer to do a semester's
    # worth of work for 500 per hour is a different offer entirely.
    price_unit: Mapped[PriceUnit | None] = mapped_column(pg_enum(PriceUnit, "price_unit"))
    status: Mapped[ResponseStatus] = mapped_column(
        pg_enum(ResponseStatus, "response_status"),
        nullable=False,
        default=ResponseStatus.SENT,
        server_default="sent",
    )

    request: Mapped[HelpRequest] = relationship(back_populates="responses")

    __table_args__ = (
        # One answer per helper per request. Repeat pitching is spam.
        UniqueConstraint("request_id", "helper_id", name="uq_request_responses_pair"),
        Index("ix_request_responses_helper", "helper_id", "status"),
        CheckConstraint(
            "price_amount IS NULL OR price_amount >= 0", name="price_non_negative"
        ),
    )


class Contact(IdMixin, TimestampMixin, Base):
    """A recorded first contact between a student and a helper.

    We do not host the conversation — it happens in Telegram. What we keep is
    that it happened, so response time and deal counts have something real
    behind them instead of being self-reported.
    """

    __tablename__ = "contacts"

    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    helper_id: Mapped[int] = mapped_column(
        ForeignKey("helper_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("offers.id", ondelete="SET NULL")
    )
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("help_requests.id", ondelete="SET NULL")
    )
    # The prefilled message we composed, as sent.
    intro_text: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["Contact", "HelpRequest", "RequestResponse"]
