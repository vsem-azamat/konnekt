"""Tell helpers about new requests: request_alerts, helper_profiles.new_request_alerts

One row per request a helper was told about, which is also what the daily
allowance counts, so a deleted request leaves its row behind. The switch defaults to on, and both are additions the
previous release never reads, so it runs unchanged beside them.

Revision ID: 87d097b5a797
Revises: 3f8a1d6c2b47
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "87d097b5a797"
down_revision: str | Sequence[str] | None = "3f8a1d6c2b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_alerts",
        sa.Column("request_id", sa.BigInteger(), nullable=True),
        sa.Column("helper_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["helper_id"],
            ["helper_profiles.user_id"],
            name=op.f("fk_request_alerts_helper_id_helper_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["help_requests.id"],
            name=op.f("fk_request_alerts_request_id_help_requests"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_alerts")),
        sa.UniqueConstraint("request_id", "helper_id", name="uq_request_alerts_pair"),
    )
    op.create_index(
        "ix_request_alerts_helper_created",
        "request_alerts",
        ["helper_id", "created_at"],
    )
    op.add_column(
        "helper_profiles",
        sa.Column(
            "new_request_alerts",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("helper_profiles", "new_request_alerts")
    op.drop_index("ix_request_alerts_helper_created", table_name="request_alerts")
    op.drop_table("request_alerts")
