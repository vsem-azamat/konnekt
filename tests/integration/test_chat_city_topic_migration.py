"""`chats.city` and `chats.topic` on PostgreSQL: the topic is one of a list there too."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled, is_captcha_enabled,"
    " created_at, modified_at, city, topic) VALUES (:id, 'approved', false, 60, false, false, now(), now(), :city, :topic)"
)


def test_a_chat_takes_a_city_and_a_listed_topic(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": -1, "city": "Praha", "topic": "dorms"})
        conn.execute(sa.text(_INSERT), {"id": -2, "city": None, "topic": None})
    with database.connect() as conn:
        rows = conn.execute(sa.text("SELECT id, city, topic FROM chats ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [(-2, None, None), (-1, "Praha", "dorms")]


def test_a_topic_outside_the_list_is_refused(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with pytest.raises(IntegrityError), database.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": -3, "city": None, "topic": "sport"})


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "b9e4c71d2a58")
    with database.connect() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("chats")}
    assert not {"city", "topic"} & columns
