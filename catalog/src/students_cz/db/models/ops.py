"""Operational tables: the query log and what people did."""

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Interval,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from students_cz.db.base import Base, CreatedAtMixin, IdMixin
from students_cz.db.models.enums import (
    ContentLang,
    UserEventKind,
    pg_enum,
)


class SearchQuery(IdMixin, CreatedAtMixin, Base):
    """Every free-text search, with what we made of it and how it went.

    This is the most valuable table in the schema and costs nothing to keep.
    Queries that returned zero results are a ranked list of what the catalog is
    missing, and raw text paired with the parse is the training data for making
    the parser better.
    """

    __tablename__ = "search_queries"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[ContentLang | None] = mapped_column(pg_enum(ContentLang, "content_lang"))

    # What the parser extracted: {"subject_id": 42, "institution_id": 3,
    # "service_type": "exam_help", "deadline": "2026-02-14"}.
    parsed: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Whether the user then corrected our chips — the cheapest possible signal
    # that the parse was wrong.
    corrected: Mapped[dict | None] = mapped_column(JSONB)

    results_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    parser: Mapped[str | None] = mapped_column(String(64))
    took: Mapped[object | None] = mapped_column(Interval)

    __table_args__ = (
        Index("ix_search_queries_created", "created_at"),
        Index("ix_search_queries_empty", "results_count", "created_at"),
        Index("ix_search_queries_parsed", "parsed", postgresql_using="gin"),
    )


class UserEvent(IdMixin, CreatedAtMixin, Base):
    """Append-only record of what people did.

    Two things it is for. The obvious one is knowing which parts of the product
    are used. The one that pays for itself is choosing who to tell about
    something: "people who searched for nostrification and never wrote to
    anyone" is a question this table can answer and a user row cannot.

    Never a source of truth — deleting the whole table must lose nothing but
    hindsight.
    """

    __tablename__ = "user_events"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[UserEventKind] = mapped_column(
        pg_enum(UserEventKind, "user_event_kind"), nullable=False
    )
    # Whatever the event needs: {"query": "матан", "results": 3},
    # {"helper_id": 42}, {"source": "instagram"}.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        # "What did this person do" and "who did this thing recently" are the
        # two questions actually asked of it.
        Index("ix_user_events_person", "user_id", "created_at"),
        Index("ix_user_events_kind", "kind", "created_at"),
        Index("ix_user_events_payload", "payload", postgresql_using="gin"),
    )


__all__ = ["SearchQuery", "UserEvent"]
