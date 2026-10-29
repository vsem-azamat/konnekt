"""Drop the nine columns nothing ever filled

Revision ID: e81c3f5a2d96
Revises: 9d4b6e2a1f70
Create Date: 2026-10-29

The second half of 9d4b6e2a1f70: the models stopped mapping these there, so the
release before this one no longer reads them (docs/invariants.md). Azamat
agreed on 2026-10-29 with all nine empty. A column that holds anything but its
default by the time this runs stops it: dropping that is a new question.

The downgrade adds them back empty, with the defaults they had, at the end of
their tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e81c3f5a2d96"
down_revision: str | Sequence[str] | None = "9d4b6e2a1f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each column, and what in it would be information rather than a default.
COLUMNS = (
    ("contacts", "replied_at", "replied_at IS NOT NULL"),
    ("helper_profiles", "reviews_count", "reviews_count <> 0"),
    ("institutions", "logo_url", "logo_url IS NOT NULL"),
    ("item_categories", "allows_rent", "NOT allows_rent"),
    ("item_categories", "allows_sale", "NOT allows_sale"),
    ("user_education", "finished_year", "finished_year IS NOT NULL"),
    ("user_education", "is_current", "NOT is_current"),
    ("user_education", "started_year", "started_year IS NOT NULL"),
    ("weekly_availability", "valid_until", "valid_until IS NOT NULL"),
)


def refuse_unless_empty(connection: sa.Connection) -> None:
    for table, column, filled in COLUMNS:
        exists = connection.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                " WHERE table_schema = current_schema()"
                " AND table_name = :table AND column_name = :column)"
            ),
            {"table": table, "column": column},
        ).scalar_one()
        if exists and connection.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {filled})")
        ).scalar_one():
            raise RuntimeError(
                f"{table}.{column} holds data; it was agreed to drop it empty."
                " Stopping."
            )


def upgrade() -> None:
    refuse_unless_empty(op.get_bind())
    for table, column, _ in COLUMNS:
        op.drop_column(table, column)


def downgrade() -> None:
    op.add_column(
        "contacts", sa.Column("replied_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "helper_profiles",
        sa.Column(
            "reviews_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column("institutions", sa.Column("logo_url", sa.String(length=512)))
    for column in ("allows_rent", "allows_sale"):
        op.add_column(
            "item_categories",
            sa.Column(
                column, sa.Boolean(), server_default=sa.text("true"), nullable=False
            ),
        )
    op.add_column(
        "user_education",
        sa.Column(
            "is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column("user_education", sa.Column("started_year", sa.Integer()))
    op.add_column("user_education", sa.Column("finished_year", sa.Integer()))
    op.add_column("weekly_availability", sa.Column("valid_until", sa.Date()))
