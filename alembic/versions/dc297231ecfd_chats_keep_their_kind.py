"""Remember whether a chat is a group or a channel.

The catalogue lists somebody else's channels beside the groups, and counts
subscribers in them rather than members. Every chat until now was a group,
so the default is the answer for the existing rows. A channel is only ever
somebody else's, so it stays external or taken down.

Revision ID: dc297231ecfd
Revises: c4f7e2a91b06
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dc297231ecfd"
down_revision: str | None = "c4f7e2a91b06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("kind", sa.String(length=16), nullable=False, server_default="group"))
    op.create_check_constraint("ck_chats_kind", "chats", "kind IN ('group', 'channel')")
    op.create_check_constraint(
        "ck_chats_channel_external", "chats", "kind = 'group' OR resource_status IN ('external', 'disabled')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_chats_channel_external", "chats", type_="check")
    op.drop_constraint("ck_chats_kind", "chats", type_="check")
    op.drop_column("chats", "kind")
