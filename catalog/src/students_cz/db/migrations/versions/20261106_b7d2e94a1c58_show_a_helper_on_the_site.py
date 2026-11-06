"""Show a helper on the site: helper_profiles.show_on_site

The owner's own consent to a page on konnekt.cz, off for everybody until they
turn it on. An addition the previous release never reads, so it runs
unchanged beside it.

Revision ID: b7d2e94a1c58
Revises: e81c3f5a2d96
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2e94a1c58"
down_revision: str | Sequence[str] | None = "e81c3f5a2d96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "helper_profiles",
        sa.Column(
            "show_on_site",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("helper_profiles", "show_on_site")
