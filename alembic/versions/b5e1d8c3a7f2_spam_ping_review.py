"""spam_pings: a moderator's verdict in the console's ads queue.

Three nullable columns and nothing else, so the previous release runs
unchanged beside it.

Revision ID: b5e1d8c3a7f2
Revises: a9c4e2d7f610
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e1d8c3a7f2"
down_revision: str | None = "a9c4e2d7f610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("spam_pings", sa.Column("verdict", sa.String(length=16), nullable=True))
    op.add_column("spam_pings", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("spam_pings", sa.Column("reviewed_by", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("spam_pings", "reviewed_by")
    op.drop_column("spam_pings", "reviewed_at")
    op.drop_column("spam_pings", "verdict")
