"""`chats.bot_absent_at` on PostgreSQL: empty for every chat after the upgrade."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration


def test_every_chat_starts_asked(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "e4b7c2d9a1f6")
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled,"
                " is_captcha_enabled, created_at, modified_at) VALUES (-1, 'approved', false, 60, false, false,"
                " now(), now())"
            )
        )
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT bot_absent_at FROM chats")).scalar_one() is None


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "e4b7c2d9a1f6")
    with database.connect() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("chats")}
    assert "bot_absent_at" not in columns
