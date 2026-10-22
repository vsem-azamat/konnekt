"""Add chats.city and chats.topic.

The catalogue filters by city and files chats under topics. Both are nullable
with no default, so nothing is placed or filed by running a migration: city
None is all of Czechia, topic None is a university's chat or an unfiled one.

Revision ID: c4d81f2a9e60
Revises: b9e4c71d2a58
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d81f2a9e60"
down_revision: str | None = "b9e4c71d2a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("city", sa.String(length=96), nullable=True))
    op.add_column("chats", sa.Column("topic", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "ck_chats_topic",
        "chats",
        "topic IN ('university', 'subjects', 'dorms', 'work_it', 'general')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chats_topic", "chats", type_="check")
    op.drop_column("chats", "topic")
    op.drop_column("chats", "city")
