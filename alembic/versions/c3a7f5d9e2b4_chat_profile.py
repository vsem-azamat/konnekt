"""chats: the rest of what getChat says (username, description, slow mode, permissions...).

Nullable columns and nothing else, so the previous release runs unchanged beside them.

Revision ID: c3a7f5d9e2b4
Revises: b5d1e8f3a2c7
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a7f5d9e2b4"
down_revision: str | None = "b5d1e8f3a2c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("username", sa.String(length=32), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("chat_type", sa.String(length=16), nullable=True),
        sa.Column("slow_mode_delay", sa.Integer(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("has_protected_content", sa.Boolean(), nullable=True),
        sa.Column("has_hidden_members", sa.Boolean(), nullable=True),
        sa.Column("has_aggressive_anti_spam_enabled", sa.Boolean(), nullable=True),
        sa.Column("message_auto_delete_time", sa.Integer(), nullable=True),
        sa.Column("linked_chat_id", sa.BigInteger(), nullable=True),
    )


def upgrade() -> None:
    for column in _columns():
        op.add_column("chats", column)


def downgrade() -> None:
    for column in reversed(_columns()):
        op.drop_column("chats", column.name)
