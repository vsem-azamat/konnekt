"""audience_days: the days each person used each touchpoint, for the console's trends.

A new table beside the audience, so the previous release runs unchanged. It is
filled from what the audience already knows for certain: the first and last
day of each touchpoint, and the day of each block that still stands. The days
between are lost, and so are blocks lifted since; the console hatches them.
The backfill's guessed dates are left out.

Revision ID: b8d4e1f6a2c7
Revises: a4f7c2e9b1d6
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4e1f6a2c7"
down_revision: str | None = "a4f7c2e9b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The backfill's guesses at private contacts were dated by when the bot first
# stored them, not by any visit: their first day is no visit, and their last
# only if they came back since.
HISTORY = """
INSERT INTO audience_days (user_id, day, touchpoint, event)
SELECT t.user_id, CAST(t.first_at AS DATE), t.touchpoint, 'visit'
FROM audience_touches t JOIN audience_members m ON m.user_id = t.user_id
WHERE m.source IS DISTINCT FROM 'backfill:dm_estimate'
UNION
SELECT t.user_id, CAST(t.last_at AS DATE), t.touchpoint, 'visit'
FROM audience_touches t JOIN audience_members m ON m.user_id = t.user_id
WHERE m.source IS DISTINCT FROM 'backfill:dm_estimate' OR t.last_at > t.first_at
UNION
SELECT user_id, CAST(blocked_at AS DATE), bot, 'block' FROM audience_reach WHERE blocked_at IS NOT NULL
"""


def upgrade() -> None:
    op.create_table(
        "audience_days",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("touchpoint", sa.String(length=16), nullable=False),
        sa.Column("event", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "touchpoint IN ('main_bot', 'contact_bot', 'mini_app', 'moved_bot')", name="ck_audience_days_touchpoint"
        ),
        sa.CheckConstraint("event IN ('visit', 'block', 'unblock')", name="ck_audience_days_event"),
        sa.ForeignKeyConstraint(["user_id"], ["audience_members.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "day", "touchpoint", "event"),
    )
    op.create_index("ix_audience_days_day", "audience_days", ["day", "touchpoint", "event"])
    op.execute(HISTORY)


def downgrade() -> None:
    op.drop_index("ix_audience_days_day", table_name="audience_days")
    op.drop_table("audience_days")
