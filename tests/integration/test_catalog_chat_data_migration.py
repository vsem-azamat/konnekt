"""The data migration that files the listed chats, on PostgreSQL."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

_INSERT = (
    "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled, is_captcha_enabled,"
    " created_at, modified_at, public_link, city, topic)"
    " VALUES (:id, 'approved', false, 60, false, false, now(), now(), :link, :city, :topic)"
)


def _row(conn, chat_id: int) -> tuple:
    return tuple(
        conn.execute(
            sa.text("SELECT city, topic, institution_code FROM chats WHERE id = :id"), {"id": chat_id}
        ).one()
    )


def test_listed_chats_are_filed_by_their_link_and_console_edits_stand(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "c4d81f2a9e60")
    with database.begin() as conn:
        conn.execute(sa.text(_INSERT), {"id": -1, "link": "https://t.me/strahov_koleje", "city": None, "topic": None})
        conn.execute(sa.text(_INSERT), {"id": -2, "link": "https://t.me/fyzika_cz/", "city": None, "topic": None})
        conn.execute(sa.text(_INSERT), {"id": -3, "link": "https://t.me/czu_chat", "city": None, "topic": None})
        # Already set in the console before the migration ran.
        conn.execute(sa.text(_INSERT), {"id": -4, "link": "https://t.me/vsb_chat", "city": "Havířov", "topic": None})
        conn.execute(sa.text(_INSERT), {"id": -5, "link": "https://t.me/someone_else", "city": None, "topic": None})

    command.upgrade(_alembic(), "head")

    with database.connect() as conn:
        assert _row(conn, -1) == ("Praha", "dorms", None)
        assert _row(conn, -2) == (None, "subjects", None)
        assert _row(conn, -3) == ("Praha", None, "czu")
        assert _row(conn, -4) == ("Havířov", "university", None)
        assert _row(conn, -5) == (None, None, None)
