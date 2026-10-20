"""chat_control_levels: a chat's status may also be observed or external.

Only a constraint, and one every existing row already meets: the previous
release writes three of the five values, so it runs unchanged beside this. No
row is changed on the way up; chats are moved to the new values from the
console. The way down disables them, since the previous release cannot read
them.

Revision ID: b3f8d1c6e925
Revises: a9c4e2d7f610
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3f8d1c6e925"
down_revision: str | None = "a9c4e2d7f610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_chats_resource_status",
        "chats",
        "resource_status IN ('discovered', 'approved', 'observed', 'external', 'disabled')",
    )


def downgrade() -> None:
    # The previous release knows neither value, and its console cannot list a
    # row carrying one. Disabled, not approved: a chat we only watched or are
    # not in must never come back moderated.
    op.execute("UPDATE chats SET resource_status = 'disabled' WHERE resource_status IN ('observed', 'external')")
    op.drop_constraint("ck_chats_resource_status", "chats", type_="check")
