"""admin_sessions keeps a SHA-256 of each session token, not the token.

The token is the HttpOnly cookie; in the table it made a copy of the table, a
backup or a careless query a list of working console sessions. Existing rows
are hashed in place, so nobody is signed out by the deploy.

It changes what the previous release reads, though not the schema: for the
minute between this migration and the new webapi, the old one finds no
session and the console asks to sign in again, and going back to that release
does the same. Signing in is opening the Mini App, so the cost is one tap.

There is no way back to the tokens: the downgrade deletes the sessions, and
everybody signs in again from the Mini App.

Revision ID: d2b7e9a4c518
Revises: c1f4a8d26b37
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2b7e9a4c518"
down_revision: str | None = "c1f4a8d26b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("UPDATE admin_sessions SET session_id = encode(sha256(convert_to(session_id, 'UTF8')), 'hex')")


def downgrade() -> None:
    op.execute("DELETE FROM admin_sessions")
