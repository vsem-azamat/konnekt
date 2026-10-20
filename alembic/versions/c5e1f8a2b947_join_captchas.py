"""join_captchas, join_waves: the join captcha in a private message and the waves that pause it.

New tables and nothing else, so the previous release runs unchanged beside them.

Revision ID: c5e1f8a2b947
Revises: b3f8d1c6e925
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e1f8a2b947"
down_revision: str | None = "b3f8d1c6e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "join_captchas",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.String(length=16), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("attempts_left", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("wave_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_join_captchas_chat_id_created_at", "join_captchas", ["chat_id", "created_at"])
    op.create_index("ix_join_captchas_status", "join_captchas", ["status"])
    op.create_index("ix_join_captchas_wave_id", "join_captchas", ["wave_id"])

    op.create_table(
        "join_waves",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_surge_at", sa.DateTime(), nullable=False),
        sa.Column("alert_message_id", sa.BigInteger(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_join_waves_chat_id", "join_waves", ["chat_id"])


def downgrade() -> None:
    op.drop_table("join_waves")
    op.drop_table("join_captchas")
