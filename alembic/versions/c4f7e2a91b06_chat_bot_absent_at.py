"""Remember which chats the bot is not in.

The hourly loop asked every chat, and the two the current bot was never added
to answered "chat not found" every hour, into the log as a warning each time.
This is when Telegram last said so; nullable, no default, so every chat is
asked again after the upgrade.

Revision ID: c4f7e2a91b06
Revises: e4b7c2d9a1f6
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f7e2a91b06"
down_revision: str | None = "e4b7c2d9a1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("bot_absent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("chats", "bot_absent_at")
