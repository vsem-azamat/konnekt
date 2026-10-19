"""The moderation record names grants, revocations and message actions.

`!admin` and `!unadmin` were only log lines, and deleting, purging and
pinning had no action at all, so "who made X a moderator here" and "who
deleted this" had no answer in the record.

Widening only, so the previous release still runs on it. The downgrade
deletes the new kinds of row, which the narrower constraint cannot hold.

Revision ID: e4a9c2b71f30
Revises: d8a3c61f5e27
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4a9c2b71f30"
down_revision: str | None = "d8a3c61f5e27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = ("ban", "unban", "kick", "mute", "unmute", "blacklist", "unblacklist")
_ADDED = ("grant", "revoke", "delete", "purge", "pin", "unpin")


def _check(actions: tuple[str, ...]) -> str:
    return "action IN (" + ", ".join(f"'{a}'" for a in actions) + ")"


def upgrade() -> None:
    # The bot keeps writing while this runs; better to fail the deploy than to
    # queue every query on the table behind a lock that cannot be had.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_moderation_events_action", "moderation_events", type_="check")
    op.create_check_constraint("ck_moderation_events_action", "moderation_events", _check(_BEFORE + _ADDED))


def downgrade() -> None:
    op.execute("DELETE FROM moderation_events WHERE " + _check(_ADDED))
    op.drop_constraint("ck_moderation_events_action", "moderation_events", type_="check")
    op.create_check_constraint("ck_moderation_events_action", "moderation_events", _check(_BEFORE))
