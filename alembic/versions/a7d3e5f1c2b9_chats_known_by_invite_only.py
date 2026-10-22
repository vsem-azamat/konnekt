"""Keep a chat known only by its invite link out of moderation.

Such a chat has no id of Telegram's: the bot is not in it, and only a member
can learn one. It gets an id of ours from below -2**52, outside the range
Telegram uses, and nothing may ask the Bot API about it. The check makes sure
it is only ever listed as somebody else's or taken down, never moderated.

Revision ID: a7d3e5f1c2b9
Revises: dc297231ecfd
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3e5f1c2b9"
down_revision: str | None = "dc297231ecfd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_chats_preview_external", "chats", "id > -4503599627370496 OR resource_status IN ('external', 'disabled')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_chats_preview_external", "chats", type_="check")
