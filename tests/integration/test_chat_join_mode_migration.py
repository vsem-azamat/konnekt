"""`chats.join_mode` on PostgreSQL: each chat starts in the mode the bot already acted in."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_BEFORE = "d8a3c5e17b42"
_INSERT = (
    "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled, is_captcha_enabled,"
    " created_at, modified_at, public_link)"
    " VALUES (:id, 'approved', false, 60, false, :captcha, now(), now(), :link)"
)


def test_each_chat_keeps_what_the_bot_did_there(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), _BEFORE)
    with database.begin() as conn:
        for id_, captcha, link in (
            (-1, True, "https://t.me/cvut_fit"),
            (-2, True, "https://t.me/+private"),
            (-3, False, "https://t.me/matfyz"),
            (-4, False, "https://t.me/+muni_fi"),
            (-5, False, "https://t.me/joinchat/old_style"),
            (-6, False, None),
        ):
            conn.execute(sa.text(_INSERT), {"id": id_, "captcha": captcha, "link": link})

    command.upgrade(_alembic(), "head")

    with database.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT id, join_mode FROM chats")).tuples().all())
    assert rows == {-1: "captcha", -2: "captcha", -3: "admins", -4: "open", -5: "open", -6: "open"}


def test_a_mode_outside_the_list_is_refused(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": -7, "captcha": False, "link": None})
    with pytest.raises(IntegrityError), database.begin() as conn:
        conn.execute(sa.text("UPDATE chats SET join_mode = 'everyone' WHERE id = -7"))


def test_a_new_chat_is_left_to_the_admins_and_the_old_column_needs_no_value(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled,"
                " created_at, modified_at) VALUES (-8, 'discovered', false, 60, false, now(), now())"
            )
        )
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT join_mode FROM chats WHERE id = -8")).scalar() == "admins"


def test_it_downgrades_with_the_captcha_where_it_was(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": -9, "captcha": False, "link": None})
        conn.execute(sa.text("UPDATE chats SET join_mode = 'captcha' WHERE id = -9"))
    command.downgrade(_alembic(), _BEFORE)
    with database.connect() as conn:
        columns = {column["name"] for column in sa.inspect(conn).get_columns("chats")}
        captcha = conn.execute(sa.text("SELECT is_captcha_enabled FROM chats WHERE id = -9")).scalar()
    assert not {"join_mode", "join_by_request"} & columns
    assert captcha is True
