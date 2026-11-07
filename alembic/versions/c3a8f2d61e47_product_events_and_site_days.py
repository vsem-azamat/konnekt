"""Product events from the Mini App, and the site's and search's days.

`product_events` is what `POST /api/public/events` writes for the console's
«Использование»; `site_days` and `search_days` are the daily import from
Cloudflare Web Analytics and Search Console for «Источники». All three are
new and start empty; the downgrade drops them.

Revision ID: c3a8f2d61e47
Revises: e2f99c8dd0b0
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a8f2d61e47"
down_revision: str | None = "e2f99c8dd0b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("screen", sa.String(length=120), nullable=True),
        sa.Column("props", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("platform", sa.String(length=12), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_events_at", "product_events", ["at"])
    op.create_index("ix_product_events_person", "product_events", ["user_id", "at"])
    op.create_index("ix_product_events_name", "product_events", ["name", "at"])
    op.create_index("ix_product_events_session", "product_events", ["session"])

    op.create_table(
        "site_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("visits", sa.Integer(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.CheckConstraint("dimension IN ('total', 'referrer', 'page')", name="ck_site_days_dimension"),
        sa.PrimaryKeyConstraint("day", "dimension", "key"),
    )
    op.create_table(
        "search_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("position", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("day", "query"),
    )


def downgrade() -> None:
    op.drop_table("search_days")
    op.drop_table("site_days")
    op.drop_index("ix_product_events_session", table_name="product_events")
    op.drop_index("ix_product_events_name", table_name="product_events")
    op.drop_index("ix_product_events_at", table_name="product_events")
    op.drop_index("ix_product_events_person", table_name="product_events")
    op.drop_table("product_events")
