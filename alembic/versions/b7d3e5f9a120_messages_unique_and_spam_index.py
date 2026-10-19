"""One row per message, and an index for the first-message spam check.

A redelivered update stored a second row, and the spam check scanned the
whole table for a text among labelled spam. Production had no duplicates when
this was written (checked 2026-10-19); a database that has some fails here,
on purpose, rather than losing rows a migration decided were the same.

Revision ID: b7d3e5f9a120
Revises: e4a9c2b71f30
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3e5f9a120"
down_revision: str | None = "e4a9c2b71f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("uq_messages_chat_message", "messages", ["chat_id", "message_id"], unique=True)
    op.create_index(
        "ix_messages_spam_text",
        "messages",
        ["message"],
        postgresql_using="hash",
        postgresql_where=sa.text("spam"),
        sqlite_where=sa.text("spam"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_spam_text", table_name="messages")
    op.drop_index("uq_messages_chat_message", table_name="messages")
