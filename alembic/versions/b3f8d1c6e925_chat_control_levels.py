"""chat_control_levels: a chat's status may also be observed or external.

Only a constraint, and one every existing row already meets: the previous
release writes three of the five values, so it runs unchanged beside this.

Production already had a CHECK of this name with the three old values, made by
hand before the migrations were squashed, and the first deploy failed creating
it again. So the upgrade replaces whatever is there, and the downgrade puts the
three-value one back rather than leaving the column unchecked. No
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


_NAME = "ck_chats_resource_status"


def upgrade() -> None:
    op.execute(f"ALTER TABLE chats DROP CONSTRAINT IF EXISTS {_NAME}")
    op.create_check_constraint(
        _NAME,
        "chats",
        "resource_status IN ('discovered', 'approved', 'observed', 'external', 'disabled')",
    )


def downgrade() -> None:
    # The previous release knows neither value, and its console cannot list a
    # row carrying one. Disabled, not approved: a chat we only watched or are
    # not in must never come back moderated. The note keeps the decision
    # readable so it can be restored by hand on the way forward; the link
    # stays, and a disabled chat is not listed.
    op.execute(
        "UPDATE chats SET relation_notes = concat_ws(E'\\n', relation_notes, 'Был ' || resource_status || ' до отката'), "
        "resource_status = 'disabled' WHERE resource_status IN ('observed', 'external')"
    )
    op.drop_constraint(_NAME, "chats", type_="check")
    op.create_check_constraint(_NAME, "chats", "resource_status IN ('discovered', 'approved', 'disabled')")
