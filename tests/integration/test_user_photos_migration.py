"""The `user_photos` migration, on PostgreSQL.

A photo must come back byte for byte, and "no photo" must be storable as a row
of its own: that row is what keeps the console from asking Telegram again.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

JPEG = bytes(range(256)) * 4


def test_a_photo_and_its_absence_both_round_trip(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO user_photos (user_id, unique_id, content, content_type, fetched_at) "
                "VALUES (1, 'u', :c, 'image/jpeg', now()), (2, NULL, NULL, 'image/jpeg', now())"
            ),
            {"c": JPEG},
        )
    with database.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT user_id, content FROM user_photos")).all())
    assert rows[1].tobytes() == JPEG
    assert rows[2] is None


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "c9a2f6d41e83")
    with database.connect() as conn:
        assert not sa.inspect(conn).has_table("user_photos")
