"""user_photos: a person's Telegram photo, kept so the console can show faces.

A new table and nothing else, so the previous release runs unchanged beside it.
It starts empty and fills as the console shows people.

Revision ID: d3f7a2b9c5e1
Revises: c9a2f6d41e83
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f7a2b9c5e1"
down_revision: str | None = "c9a2f6d41e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_photos",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("unique_id", sa.String(length=64), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_photos")
