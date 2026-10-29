"""Migration b6e1f4a8c203 against production's shape: eight tables nothing maps."""

from __future__ import annotations

import importlib.util

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import ROOT, _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_BEFORE = "a4c9e2f70b18"
_spec = importlib.util.spec_from_file_location(
    "b6e1f4a8c203", ROOT / "alembic" / "versions" / "b6e1f4a8c203_drop_channel_and_agent_tables.py"
)
assert _spec is not None
assert _spec.loader is not None
_THIS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_THIS)
_TABLES = set(_THIS.ARCHIVED + _THIS.UNSAVED)


def _as_production(engine: sa.Engine) -> None:
    """The database at the previous revision, carrying the tables as production does."""
    command.upgrade(_alembic(), _BEFORE)
    with engine.begin() as conn:
        for statement in _THIS._SCHEMA:
            conn.execute(sa.text(statement))


def _tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def test_the_tables_go_and_nothing_else_does(database) -> None:  # noqa: F811
    _as_production(database)
    with database.begin() as conn:
        conn.execute(sa.text("INSERT INTO channels (name) VALUES ('archived before the drop')"))
    before = _tables(database)

    command.upgrade(_alembic(), "head")

    assert before - _tables(database) == _TABLES


def test_a_fresh_database_never_had_them(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    assert not _tables(database) & _TABLES


@pytest.mark.parametrize("table", ["ad_leads", "agent_decisions", "agent_escalations"])
def test_rows_that_were_never_exported_stop_it(database, table) -> None:  # noqa: F811
    _as_production(database)
    columns = {
        "ad_leads": "(chat_id, user_id) VALUES (1, 2)",
        "agent_decisions": "(event_type, chat_id, target_user_id, action, reason) VALUES ('report', 1, 2, 'ban', 'x')",
        "agent_escalations": "(chat_id, target_user_id, suggested_action, reason, timeout_at)"
        " VALUES (1, 2, 'ban', 'x', now())",
    }[table]
    with database.begin() as conn:
        conn.execute(sa.text(f"INSERT INTO {table} {columns}"))

    with pytest.raises(RuntimeError, match=table):
        command.upgrade(_alembic(), "head")
    assert _tables(database) >= _TABLES


def test_it_downgrades_to_the_empty_tables(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), _BEFORE)
    assert _tables(database) >= _TABLES
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM channel_posts")).scalar() == 0


def test_with_pgvector_the_embedding_comes_back_too(database) -> None:  # noqa: F811
    """Production has the extension; a database without it gets the table less that one column."""
    with database.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), _BEFORE)
    with database.connect() as conn:
        column = conn.execute(
            sa.text(
                "SELECT udt_name FROM information_schema.columns WHERE table_name = 'channel_posts' AND column_name = 'embedding'"
            )
        ).scalar()
        index = conn.execute(sa.text("SELECT to_regclass('ix_channel_posts_embedding')")).scalar()
    assert column == "vector"
    assert index is not None
