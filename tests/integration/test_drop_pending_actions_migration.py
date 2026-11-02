"""Migration e2f99c8dd0b0: the MCP proposals' table goes, and only while it is empty."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_BEFORE = "b8d4e1f6a2c7"


def _tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def test_the_table_goes_and_nothing_else_does(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), _BEFORE)
    before = _tables(database)

    command.upgrade(_alembic(), "head")

    assert before - _tables(database) == {"pending_actions"}


def test_a_row_stops_it(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), _BEFORE)
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO pending_actions (origin, initiator_id, action, target_user_id, params, status, expires_at,"
                " created_at) VALUES ('mcp', 1, 'ban', 2, '{}', 'pending', now(), now())"
            )
        )

    with pytest.raises(RuntimeError, match="pending_actions"):
        command.upgrade(_alembic(), "head")
    assert "pending_actions" in _tables(database)


def test_it_downgrades_to_the_empty_table(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), _BEFORE)
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM pending_actions")).scalar() == 0
