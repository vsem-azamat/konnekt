"""spam_pings: a moderator's verdict, for the console's ads queue.

Three nullable columns, a check on the verdict and a partial index for the
queue, so the previous release runs unchanged beside it. The hits of people
already on the blacklist are answered «ad», as a ban from now on answers them.

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
    op.create_check_constraint("ck_spam_pings_verdict", "spam_pings", "verdict IN ('done', 'not_ad', 'ad')")
    op.create_index(
        "ix_spam_pings_unreviewed",
        "spam_pings",
        ["detected_at", "id"],
        postgresql_where=sa.text("verdict IS NULL"),
    )
    op.execute(
        "UPDATE spam_pings SET verdict = 'ad' "
        "WHERE verdict IS NULL AND user_id IN (SELECT id FROM users WHERE blocked)"
    )


def downgrade() -> None:
    op.drop_index("ix_spam_pings_unreviewed", table_name="spam_pings")
    op.drop_constraint("ck_spam_pings_verdict", "spam_pings", type_="check")
    op.drop_column("spam_pings", "reviewed_by")
    op.drop_column("spam_pings", "reviewed_at")
    op.drop_column("spam_pings", "verdict")
