"""Add join_captchas.reminded_at.

The captcha reminds an applicant who has not answered, once. The time is stored
so that a restart, or a refused message, does not send a second one.

Revision ID: b9e4c71d2a58
Revises: a7c3e91d5b24
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9e4c71d2a58"
down_revision: str | None = "a7c3e91d5b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("join_captchas", sa.Column("reminded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("join_captchas", "reminded_at")
