"""Partner placements — insurance, visa language courses, bank statements,
sworn translations.

This is not catalog content and must never be searchable alongside it. A
placement is a rule: *show this block in this slot when this condition holds*.
Keeping the condition as JSONB rather than columns means a new targeting idea
("only in September", "only for users whose UI language is Ukrainian") is a row,
not a migration.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from students_cz.db.base import Base, CreatedAtMixin, IdMixin, TimestampMixin
from students_cz.db.models.enums import (
    PayoutModel,
    PlacementEventKind,
    PlacementSlot,
    UiLang,
    pg_enum,
)


class Partner(IdMixin, TimestampMixin, Base):
    __tablename__ = "partners"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(240))
    payout_model: Mapped[PayoutModel] = mapped_column(
        pg_enum(PayoutModel, "payout_model"),
        nullable=False,
        default=PayoutModel.CPC,
        server_default="cpc",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    offers: Mapped[list["PartnerOffer"]] = relationship(
        back_populates="partner", cascade="all, delete-orphan"
    )


class PartnerOffer(IdMixin, TimestampMixin, Base):
    __tablename__ = "partner_offers"

    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)

    # The card renders a two-letter monogram on a tinted square instead of a
    # logo file — no asset pipeline, and it survives a partner rebrand.
    logo_text: Mapped[str | None] = mapped_column(String(4))
    logo_bg: Mapped[str | None] = mapped_column(String(9))

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A card on the home showcase quotes a number, drawn «от … Kč», where the
    # older cards' `price_text` is free text.
    price_from: Mapped[int | None] = mapped_column(Integer)
    # The showcase card's cover, by the hash of its bytes.
    photo: Mapped[str | None] = mapped_column(
        ForeignKey("partner_photos.sha256", ondelete="RESTRICT")
    )

    partner: Mapped[Partner] = relationship(back_populates="offers")
    texts: Mapped[list["PartnerOfferI18n"]] = relationship(
        back_populates="offer", cascade="all, delete-orphan", lazy="selectin"
    )
    placements: Mapped[list["Placement"]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )


class PartnerOfferI18n(Base):
    __tablename__ = "partner_offer_i18n"

    offer_id: Mapped[int] = mapped_column(
        ForeignKey("partner_offers.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[UiLang] = mapped_column(pg_enum(UiLang, "ui_lang"), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(240))
    # Free text rather than a number: partners quote "from 8 900", "0 Kč",
    # "450 Kč / page".
    price_text: Mapped[str | None] = mapped_column(String(64))
    # The line that explains why this is relevant at all, in our voice.
    context_note: Mapped[str | None] = mapped_column(Text)

    offer: Mapped[PartnerOffer] = relationship(back_populates="texts")


class Placement(IdMixin, TimestampMixin, Base):
    __tablename__ = "placements"

    offer_id: Mapped[int] = mapped_column(
        ForeignKey("partner_offers.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[PlacementSlot] = mapped_column(
        pg_enum(PlacementSlot, "placement_slot"), nullable=False
    )
    # Matched against the request context by the application, e.g.
    # {"service_type": "nostrification"}, {"month": [8, 9]}, {"ui_lang": ["uk"]}.
    # An empty object means "always, in this slot".
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # When a showcase card first went live. Unset with `is_active` off is a
    # draft; set with it off, a card taken down. The older slots never set it.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    offer: Mapped[PartnerOffer] = relationship(back_populates="placements")

    __table_args__ = (
        Index("ix_placements_slot_active", "slot", "is_active", "priority"),
        Index("ix_placements_conditions", "conditions", postgresql_using="gin"),
    )


class PartnerPhoto(CreatedAtMixin, Base):
    """A showcase card's photo, kept in the database by the hash of its bytes.

    The hash is the address it is served at, so the address names one picture
    for ever and can be cached as immutable; a new photo is a new row and a new
    address. Never deleted: a card taken down keeps what it showed.
    """

    __tablename__ = "partner_photos"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    mime: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class PlacementEvent(IdMixin, CreatedAtMixin, Base):
    """Impressions and clicks.

    High-volume and append-only. Worth partitioning by month once it hurts;
    until then a plain table with a created_at index is enough.
    """

    __tablename__ = "placement_events"

    placement_id: Mapped[int] = mapped_column(
        ForeignKey("placements.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[PlacementEventKind] = mapped_column(
        pg_enum(PlacementEventKind, "placement_event_kind"), nullable=False
    )

    __table_args__ = (
        Index("ix_placement_events_rollup", "placement_id", "kind", "created_at"),
    )


__all__ = [
    "Partner",
    "PartnerOffer",
    "PartnerOfferI18n",
    "PartnerPhoto",
    "Placement",
    "PlacementEvent",
]
