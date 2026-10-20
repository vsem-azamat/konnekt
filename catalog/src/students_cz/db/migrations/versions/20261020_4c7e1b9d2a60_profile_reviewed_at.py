"""An operator's look at a profile: helper_profiles.reviewed_at

A nullable column, so the previous release runs unchanged beside it. The
console's queue holds every listed profile nobody looked at, however old; the
ones out for more than a week are counted as looked at, so it opens on the
last week's and not on the whole catalog.

Revision ID: 4c7e1b9d2a60
Revises: 6e528db59a57
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c7e1b9d2a60"
down_revision: str | Sequence[str] | None = "6e528db59a57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "helper_profiles",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE helper_profiles SET reviewed_at = now() "
        "WHERE published_at < now() - interval '7 days'"
    )


def downgrade() -> None:
    op.drop_column("helper_profiles", "reviewed_at")
