"""A tap on a chat's join button in the catalog lets its person in without a captcha.

Revision ID: c9a2f6d41e83
Revises: b8e1f4c6d2a0
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a2f6d41e83"
down_revision: str | None = "b8e1f4c6d2a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_passes",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "chat_id"),
    )
    op.create_index("ix_catalog_passes_expires_at", "catalog_passes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_catalog_passes_expires_at", table_name="catalog_passes")
    op.drop_table("catalog_passes")
