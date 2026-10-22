"""chats.join_mode in place of is_captcha_enabled, and chats.join_by_request.

The mode each chat gets is what the bot already did there, so nothing changes
for anyone on the day:

- captcha on: captcha;
- a public chat (its link is a username) without it: admins, since Telegram's
  own requests, where it has them on, were left to the admins;
- a listed private chat without it: open, since its bot link asked for no
  request and people walked in;
- an approved chat without a link: open too, ADMINS would give it a link
  asking for requests nobody answers once listed (every one was private when
  this was written);
- any other chat without a link: admins, the bot acting in none of them yet
  and some of them perhaps public.

OPEN approves requests only in a public chat, so in a private one requests
that come by an admin's own link still wait for the admins, as before.

is_captcha_enabled stays in the table, given a default, so the previous release
keeps running beside this one; a later migration drops it.

Revision ID: e4b7c2d9a1f6
Revises: d8a3c5e17b42
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c2d9a1f6"
down_revision: str | None = "d8a3c5e17b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("join_mode", sa.String(length=16), server_default="admins", nullable=False))
    op.add_column("chats", sa.Column("join_by_request", sa.Boolean(), nullable=True))
    op.create_check_constraint("ck_chats_join_mode", "chats", "join_mode IN ('open', 'captcha', 'admins')")
    op.execute(
        """
        UPDATE chats SET join_mode = CASE
            WHEN is_captcha_enabled THEN 'captcha'
            WHEN public_link IS NOT NULL AND public_link NOT LIKE '%/+%'
                AND public_link NOT LIKE '%joinchat%' THEN 'admins'
            WHEN public_link IS NULL AND resource_status <> 'approved' THEN 'admins'
            ELSE 'open'
        END
        """
    )
    op.alter_column("chats", "is_captcha_enabled", server_default=sa.false())


def downgrade() -> None:
    op.execute("UPDATE chats SET is_captcha_enabled = (join_mode = 'captcha')")
    op.alter_column("chats", "is_captcha_enabled", server_default=None)
    op.drop_constraint("ck_chats_join_mode", "chats", type_="check")
    op.drop_column("chats", "join_by_request")
    op.drop_column("chats", "join_mode")
