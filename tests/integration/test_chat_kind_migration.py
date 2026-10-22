"""`chats.kind` on PostgreSQL: every existing chat is a group, and a channel stays somebody else's."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled,"
    " is_captcha_enabled, created_at, modified_at{kind}) VALUES ({id}, '{status}', false, 60, false, false,"
    " now(), now(){value})"
)


def _insert(conn, *, id: int, status: str, kind: str | None = None) -> None:
    conn.execute(
        sa.text(
            _INSERT.format(id=id, status=status, kind=", kind" if kind else "", value=f", '{kind}'" if kind else "")
        )
    )


def test_every_existing_chat_is_a_group(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "c4f7e2a91b06")
    with database.begin() as conn:
        _insert(conn, id=-1, status="approved")
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT kind FROM chats")).scalar_one() == "group"


@pytest.mark.parametrize(("status", "kind"), [("external", "private"), ("approved", "channel")])
def test_the_database_refuses_what_cannot_be(database, status, kind) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with pytest.raises(IntegrityError), database.begin() as conn:
        _insert(conn, id=-1, status=status, kind=kind)


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        _insert(conn, id=-1, status="external", kind="channel")
    command.downgrade(_alembic(), "c4f7e2a91b06")
    with database.connect() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("chats")}
    assert "kind" not in columns
