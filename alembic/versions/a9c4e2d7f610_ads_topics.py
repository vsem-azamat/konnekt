"""ads_topics: which staff forum topic holds whose conversation with the ads bot (#265).

A new table and nothing else, so the previous release runs unchanged beside it.

Revision ID: a9c4e2d7f610
Revises: d2b7e9a4c518
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e2d7f610"
down_revision: str | None = "d2b7e9a4c518"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ads_topics",
        sa.Column("group_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
        sa.UniqueConstraint("group_id", "thread_id", name="uq_ads_topics_group_id_thread_id"),
    )


def downgrade() -> None:
    op.drop_table("ads_topics")
