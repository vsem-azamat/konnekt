"""`chats.migrated_to_chat_id` on PostgreSQL: empty for every chat after the upgrade."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_kind_migration import _insert
from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration


def test_every_chat_starts_as_itself(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "a7d3e5f1c2b9")
    with database.begin() as conn:
        _insert(conn, id=-1, status="approved")
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT migrated_to_chat_id FROM chats")).scalar_one() is None


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "a7d3e5f1c2b9")
    with database.connect() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("chats")}
    assert "migrated_to_chat_id" not in columns
