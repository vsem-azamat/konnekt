"""audience: everybody who has used one of our bots or the Mini App.

New tables and nothing else, so the previous release runs unchanged beside it.

Revision ID: e5d2a7c4b913
Revises: a9c4e2d7f610
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5d2a7c4b913"
down_revision: str | None = "a9c4e2d7f610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audience_members",
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("is_premium", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("opted_out_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_audience_members_last_seen_at"), "audience_members", ["last_seen_at"])
    op.create_table(
        "audience_touches",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("touchpoint", sa.String(length=16), nullable=False),
        sa.Column("first_at", sa.DateTime(), nullable=False),
        sa.Column("last_at", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "touchpoint IN ('main_bot', 'contact_bot', 'mini_app', 'moved_bot')", name="ck_audience_touches_touchpoint"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["audience_members.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "touchpoint"),
    )
    op.create_table(
        "audience_reach",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("bot", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("bot IN ('main_bot', 'contact_bot')", name="ck_audience_reach_bot"),
        sa.PrimaryKeyConstraint("user_id", "bot"),
    )


def downgrade() -> None:
    op.drop_table("audience_reach")
    op.drop_table("audience_touches")
    op.drop_index(op.f("ix_audience_members_last_seen_at"), table_name="audience_members")
    op.drop_table("audience_members")
