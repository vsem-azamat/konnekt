"""Partner showcase on home: a home slot, photos, «от … Kč», publish date

Revision ID: c4e1a7b93d20
Revises: 5b2e8f1c9a03
Create Date: 2026-10-29

Only additions, so the release before this one runs on the new schema: one
enum value, one table, three nullable columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1a7b93d20"
down_revision: str | Sequence[str] | None = "5b2e8f1c9a03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: a database stamped from metadata already has it.
    op.execute("ALTER TYPE placement_slot ADD VALUE IF NOT EXISTS 'home_life'")
    op.create_table(
        "partner_photos",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime", sa.String(length=32), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_partner_photos")),
    )
    op.add_column("partner_offers", sa.Column("price_from", sa.Integer()))
    op.add_column("partner_offers", sa.Column("photo", sa.String(length=64)))
    op.create_foreign_key(
        op.f("fk_partner_offers_photo_partner_photos"),
        "partner_offers",
        "partner_photos",
        ["photo"],
        ["sha256"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "placements", sa.Column("published_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    """The columns and the table go; the enum value stays, as Postgres cannot
    drop one."""
    op.drop_column("placements", "published_at")
    op.drop_constraint(
        op.f("fk_partner_offers_photo_partner_photos"),
        "partner_offers",
        type_="foreignkey",
    )
    op.drop_column("partner_offers", "photo")
    op.drop_column("partner_offers", "price_from")
    op.drop_table("partner_photos")
