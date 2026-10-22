"""When the author closed a request: help_requests.closed_at

Nullable, so the previous release runs unchanged beside it. Requests closed
before this have none, and the author's list shows them closed without a date.

Revision ID: 3f8a1d6c2b47
Revises: 7d3a5c0e9b14
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8a1d6c2b47"
down_revision: str | Sequence[str] | None = "7d3a5c0e9b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "help_requests",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("help_requests", "closed_at")
