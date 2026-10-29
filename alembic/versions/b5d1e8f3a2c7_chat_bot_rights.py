"""chat_bot_rights and its history: what the bot is and may do in each chat.

New tables and nothing else, so the previous release runs unchanged beside them.

Revision ID: b5d1e8f3a2c7
Revises: b6e1f4a8c203
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d1e8f3a2c7"
down_revision: str | None = "b6e1f4a8c203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_bot_rights",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rights", sa.JSON(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("known_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "chat_bot_rights_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rights", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.BigInteger(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_bot_rights_changes_chat_id_changed_at", "chat_bot_rights_changes", ["chat_id", "changed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_bot_rights_changes_chat_id_changed_at", table_name="chat_bot_rights_changes")
    op.drop_table("chat_bot_rights_changes")
    op.drop_table("chat_bot_rights")
