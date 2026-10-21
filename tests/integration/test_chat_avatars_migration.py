"""The `chat_avatars` migration, on PostgreSQL, and what the table must do there.

The unit tests run on SQLite, which does not enforce the foreign key unless told
to and stores blobs loosely. Here the real column types and the cascade are
exercised: a chat that is deleted must take its picture with it, and a picture
must come back byte for byte.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

JPEG = bytes(range(256)) * 4


def test_the_table_round_trips_bytes_and_follows_its_chat(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chats (id, resource_status, is_forum, time_delete, is_welcome_enabled, is_captcha_enabled, created_at, modified_at) VALUES (-1, 'approved', false, 60, false, false, now(), now())"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO chat_avatars (chat_id, unique_id, content, content_type, fetched_at) VALUES (-1, 'u', :c, 'image/jpeg', now())"
            ),
            {"c": JPEG},
        )
    with database.connect() as conn:
        assert (
            conn.execute(sa.text("SELECT content FROM chat_avatars WHERE chat_id = -1")).scalar_one().tobytes() == JPEG
        )

    with database.begin() as conn:
        conn.execute(sa.text("DELETE FROM chats WHERE id = -1"))
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM chat_avatars")).scalar_one() == 0


def test_a_picture_cannot_outlive_a_chat_that_never_existed(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with pytest.raises(IntegrityError), database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chat_avatars (chat_id, unique_id, content, content_type, fetched_at) VALUES (-9, 'u', :c, 'image/jpeg', now())"
            ),
            {"c": JPEG},
        )


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "b5e1d8c3a7f2")
    with database.connect() as conn:
        assert not sa.inspect(conn).has_table("chat_avatars")
