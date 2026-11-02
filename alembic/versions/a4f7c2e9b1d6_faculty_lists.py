"""faculty_lists: the message a university chat pins with its faculties' chats.

A new table, so the previous release runs unchanged beside it.

Revision ID: a4f7c2e9b1d6
Revises: d9b2e6a4c8f1
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f7c2e9b1d6"
down_revision: str | None = "d9b2e6a4c8f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faculty_lists",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("button_url", sa.Text(), nullable=False),
        sa.Column("pinned_at", sa.DateTime(), nullable=True),
        sa.Column("gone_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    op.drop_table("faculty_lists")
