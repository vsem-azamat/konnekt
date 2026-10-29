"""Captcha in the chat: a chat may let applicants in muted and ask there.

New nullable or defaulted columns only, so the previous release runs unchanged beside it.

Revision ID: c7e2a9f41d03
Revises: b6e1f4a8c203
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a9f41d03"
down_revision: str | None = "b6e1f4a8c203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("captcha_in_chat", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("join_captchas", sa.Column("in_chat", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("join_captchas", sa.Column("card_message_id", sa.BigInteger(), nullable=True))
    op.add_column("join_captchas", sa.Column("announced_at", sa.DateTime(), nullable=True))
    op.add_column("join_captchas", sa.Column("asked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("join_captchas", "asked_at")
    op.drop_column("join_captchas", "announced_at")
    op.drop_column("join_captchas", "card_message_id")
    op.drop_column("join_captchas", "in_chat")
    op.drop_column("chats", "captcha_in_chat")
