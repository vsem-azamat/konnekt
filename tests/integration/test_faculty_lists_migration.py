"""`faculty_lists` on PostgreSQL: the table comes and goes with its migration."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration


def test_it_upgrades_and_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        assert sa.inspect(conn).has_table("faculty_lists")
    command.downgrade(_alembic(), "d9b2e6a4c8f1")
    with database.connect() as conn:
        assert not sa.inspect(conn).has_table("faculty_lists")
