"""Why an operator hid a profile: helper_profiles.hidden_reason, hidden_note

Both nullable, so the previous release runs unchanged beside them. Profiles
hidden before this have no reason, and their owners are told only who hid them.

An owner's edit to a hidden profile now clears reviewed_at and puts it back on
the console's queue, so a hidden one with none would read there as edited:
those hidden before reviewed_at existed are counted as looked at.

Revision ID: 7d3a5c0e9b14
Revises: 4c7e1b9d2a60
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d3a5c0e9b14"
down_revision: str | Sequence[str] | None = "4c7e1b9d2a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASON = postgresql.ENUM("spam", "misleading", "rules", "other", name="hide_reason")


def upgrade() -> None:
    REASON.create(op.get_bind())
    op.add_column(
        "helper_profiles",
        sa.Column(
            "hidden_reason",
            postgresql.ENUM(name="hide_reason", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "helper_profiles", sa.Column("hidden_note", sa.String(200), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_helper_profiles_reason_only_when_banned"),
        "helper_profiles",
        "hidden_reason IS NULL OR status = 'banned'",
    )
    op.create_check_constraint(
        op.f("ck_helper_profiles_note_only_for_other"),
        "helper_profiles",
        "hidden_note IS NULL OR hidden_reason = 'other'",
    )
    op.execute(
        "UPDATE helper_profiles SET reviewed_at = now() "
        "WHERE status = 'banned' AND reviewed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_helper_profiles_note_only_for_other"), "helper_profiles", type_="check"
    )
    op.drop_constraint(
        op.f("ck_helper_profiles_reason_only_when_banned"),
        "helper_profiles",
        type_="check",
    )
    op.drop_column("helper_profiles", "hidden_note")
    op.drop_column("helper_profiles", "hidden_reason")
    REASON.drop(op.get_bind())
