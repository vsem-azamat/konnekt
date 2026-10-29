"""Record opening the offer screen: user_event_kind gains offer_open

Revision ID: 5b2e8f1c9a03
Revises: 87d097b5a797
Create Date: 2026-10-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "5b2e8f1c9a03"
down_revision: str | Sequence[str] | None = "87d097b5a797"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS, as for the earlier event kinds: a database stamped from
    # metadata already has it.
    op.execute("ALTER TYPE user_event_kind ADD VALUE IF NOT EXISTS 'offer_open'")


def downgrade() -> None:
    """Nothing: Postgres cannot drop a value from an enum, and one unused
    member costs less than rewriting the column to remove it."""
