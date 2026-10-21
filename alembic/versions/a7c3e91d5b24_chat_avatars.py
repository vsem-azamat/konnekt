"""chat_avatars: each chat's photo, kept so the Mini App can show it.

A new table and nothing else, so the previous release runs unchanged beside it.
It starts empty and the snapshot loop fills it on its next tick.

Revision ID: a7c3e91d5b24
Revises: b5e1d8c3a7f2
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91d5b24"
down_revision: str | None = "b5e1d8c3a7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_avatars",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("unique_id", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index("ix_chat_avatars_unique_id", "chat_avatars", ["unique_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_avatars_unique_id", table_name="chat_avatars")
    op.drop_table("chat_avatars")
