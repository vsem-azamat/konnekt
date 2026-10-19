"""An index on messages.timestamp, for the public catalogue's activity window.

The catalogue counts each chat's messages in the last weeks on requests
anybody can make, and without this every count read the whole table.

Revision ID: c1f4a8d26b37
Revises: b7d3e5f9a120
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1f4a8d26b37"
down_revision: str | None = "b7d3e5f9a120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The bot keeps writing while this runs; better to fail the deploy than to
    # queue every query on the table behind a lock that cannot be had.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index("ix_messages_timestamp", "messages", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_messages_timestamp", table_name="messages")
