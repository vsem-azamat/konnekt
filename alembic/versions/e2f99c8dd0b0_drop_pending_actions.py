"""Drop pending_actions, the MCP control plane's proposals awaiting a press.

The plane and everything that read the table left in #482. It never held a row
on production (count 0 on 2026-11-02, before and after that deploy), so there
is nothing to export; the upgrade refuses to run if it finds one anyway.

The downgrade recreates it empty, as the initial schema made it.

Revision ID: e2f99c8dd0b0
Revises: b8d4e1f6a2c7
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f99c8dd0b0"
down_revision: str | None = "b8d4e1f6a2c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().select_from(sa.table("pending_actions")))):
        raise RuntimeError("pending_actions has rows; export them before dropping it")
    op.drop_table("pending_actions")


def downgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("initiator_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("target_user_id", sa.BigInteger(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("admin_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('ban', 'blacklist')", name="ck_pending_actions_action"),
        sa.CheckConstraint("origin IN ('mcp')", name="ck_pending_actions_origin"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_actions_chat_id"), "pending_actions", ["chat_id"], unique=False)
    op.create_index(op.f("ix_pending_actions_initiator_id"), "pending_actions", ["initiator_id"], unique=False)
    op.create_index("ix_pending_actions_status_expires_at", "pending_actions", ["status", "expires_at"], unique=False)
    op.create_index(op.f("ix_pending_actions_target_user_id"), "pending_actions", ["target_user_id"], unique=False)
