"""Remember the supergroup a group became.

Telegram gives a supergroup an id of its own, and answers every later call
about the old group's id with "group chat was upgraded to a supergroup". The
row stays, with its history; this says where the chat went, so the hourly
loop stops asking it.

Revision ID: b8e1f4c6d2a0
Revises: a7d3e5f1c2b9
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e1f4c6d2a0"
down_revision: str | None = "a7d3e5f1c2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("migrated_to_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "migrated_to_chat_id")
