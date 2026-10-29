"""Drop rentals, study materials and moderation verdicts

Revision ID: 9d4b6e2a1f70
Revises: c4e1a7b93d20
Create Date: 2026-10-29

Three tables nothing ever wrote, and their seven types; Azamat agreed on
2026-10-29 with all three empty. The release before maps them and reads
nothing from them, so it runs on this schema. A table that has rows by the
time this runs stops it: dropping that is a new question.

The nine empty columns the models stopped mapping in the same release are
dropped by the next migration, once no release that reads them can come back.

The downgrade recreates the tables empty, as the initial schema made them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9d4b6e2a1f70"
down_revision: str | Sequence[str] | None = "c4e1a7b93d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("moderation_reviews", "materials", "items")
TYPES = (
    "item_kind",
    "item_condition",
    "item_status",
    "material_kind",
    "material_access",
    "moderated_entity",
    "moderation_verdict",
)


def refuse_unless_empty(connection: sa.Connection) -> None:
    for table in TABLES:
        exists = connection.execute(
            sa.text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table}
        ).scalar_one()
        if exists and connection.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")
        ).scalar_one():
            raise RuntimeError(
                f"{table} has rows; it was agreed to drop it empty. Stopping."
            )


def upgrade() -> None:
    refuse_unless_empty(op.get_bind())
    for table in TABLES:
        op.drop_table(table)
    for name in TYPES:
        op.execute(f"DROP TYPE {name}")


def downgrade() -> None:
    content_lang = postgresql.ENUM(name="content_lang", create_type=False)
    price_unit = postgresql.ENUM(name="price_unit", create_type=False)
    item_status = sa.Enum(
        "draft", "published", "reserved", "hidden", "archived", name="item_status"
    )

    op.create_table(
        "moderation_reviews",
        sa.Column(
            "entity_type",
            sa.Enum(
                "helper_profile",
                "offer",
                "request",
                "item",
                "material",
                name="moderated_entity",
            ),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum("auto_ok", "needs_review", "rejected", name="moderation_verdict"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=96), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moderation_reviews")),
    )
    op.create_index(
        "ix_moderation_reviews_entity",
        "moderation_reviews",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index(
        "ix_moderation_reviews_queue", "moderation_reviews", ["verdict", "created_at"]
    )

    op.create_table(
        "items",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Enum("rent", "sale", name="item_kind"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lang", content_lang, server_default="ru", nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("price_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "price_currency", sa.String(length=3), server_default="CZK", nullable=False
        ),
        sa.Column("price_unit", price_unit, server_default="day", nullable=False),
        sa.Column("deposit_amount", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "condition",
            sa.Enum("new", "good", "used", name="item_condition"),
            nullable=True,
        ),
        sa.Column("city", sa.String(length=96), nullable=True),
        sa.Column("pickup_note", sa.String(length=240), nullable=True),
        sa.Column(
            "photos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", item_status, server_default="draft", nullable=False),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "deposit_amount IS NULL OR deposit_amount >= 0",
            name=op.f("ck_items_deposit_non_negative"),
        ),
        sa.CheckConstraint(
            "price_amount IS NULL OR price_amount >= 0",
            name=op.f("ck_items_price_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["item_categories.id"],
            name=op.f("fk_items_category_id_item_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_items_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_items_subject_id_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
    )
    op.create_index("ix_items_attrs", "items", ["attrs"], postgresql_using="gin")
    op.create_index("ix_items_browse", "items", ["status", "kind", "category_id"])
    op.create_index("ix_items_city", "items", ["city"])
    op.create_index(op.f("ix_items_owner_id"), "items", ["owner_id"])
    op.create_index(op.f("ix_items_subject_id"), "items", ["subject_id"])

    op.create_table(
        "materials",
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("institution_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "notes",
                "past_exams",
                "template",
                "course",
                "other",
                name="material_kind",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lang", content_lang, server_default="ru", nullable=False),
        sa.Column(
            "files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "access",
            sa.Enum("free", "on_request", "paid", name="material_access"),
            server_default="on_request",
            nullable=False,
        ),
        sa.Column("price_stars", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="item_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "downloads_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "access <> 'paid' OR price_stars IS NOT NULL",
            name=op.f("ck_materials_paid_needs_price"),
        ),
        sa.CheckConstraint(
            "price_stars IS NULL OR price_stars > 0",
            name=op.f("ck_materials_stars_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_materials_author_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name=op.f("fk_materials_institution_id_institutions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_materials_subject_id_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_materials")),
    )
    op.create_index(op.f("ix_materials_author_id"), "materials", ["author_id"])
    op.create_index(
        "ix_materials_browse", "materials", ["status", "kind", "subject_id"]
    )
    op.create_index(
        op.f("ix_materials_institution_id"), "materials", ["institution_id"]
    )
    op.create_index(op.f("ix_materials_subject_id"), "materials", ["subject_id"])
