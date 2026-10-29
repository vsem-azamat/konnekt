"""welcome_greetings: when each chat greeting is to be deleted, so a restart cannot leave one up.

A new table and nothing else, so the previous release runs unchanged beside it.

Revision ID: a4c9e2f70b18
Revises: d3f7a2b9c5e1
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c9e2f70b18"
down_revision: str | None = "d3f7a2b9c5e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "welcome_greetings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("delete_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_welcome_greetings_chat_id_message_id", "welcome_greetings", ["chat_id", "message_id"])
    op.create_index(op.f("ix_welcome_greetings_delete_at"), "welcome_greetings", ["delete_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_welcome_greetings_delete_at"), table_name="welcome_greetings")
    op.drop_index("ix_welcome_greetings_chat_id_message_id", table_name="welcome_greetings")
    op.drop_table("welcome_greetings")
