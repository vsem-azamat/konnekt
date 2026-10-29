"""chat_members: what each person is in each chat; users: language and Premium.

A new table and nullable columns, so the previous release runs unchanged beside them.

Revision ID: d9b2e6a4c8f1
Revises: c7e2a9f41d03
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9b2e6a4c8f1"
down_revision: str | None = "c7e2a9f41d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_members",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rights", sa.JSON(), nullable=False),
        sa.Column("until_date", sa.DateTime(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("known_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("chat_id", "user_id"),
    )
    op.create_index("ix_chat_members_user_id", "chat_members", ["user_id"])
    op.add_column("users", sa.Column("language_code", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("is_premium", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "is_premium")
    op.drop_column("users", "language_code")
    op.drop_index("ix_chat_members_user_id", table_name="chat_members")
    op.drop_table("chat_members")
