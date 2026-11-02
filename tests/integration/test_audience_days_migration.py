"""The `audience_days` migration, on PostgreSQL: it starts from what is known for certain."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

BEFORE = "a4f7c2e9b1d6"


def test_history_fills_first_and_last_days_and_standing_blocks(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), BEFORE)
    with database.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO audience_members (user_id, first_seen_at, last_seen_at) VALUES "
                "(1, '2026-10-20 09:00', '2026-11-01 23:59'), (2, '2026-10-21 10:00', '2026-10-21 10:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO audience_touches (user_id, touchpoint, first_at, last_at, count) VALUES "
                "(1, 'mini_app', '2026-10-20 09:00', '2026-11-01 23:59', 7), "
                "(2, 'main_bot', '2026-10-21 10:00', '2026-10-21 10:00', 1)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO audience_reach (user_id, bot, started_at, blocked_at, known_at) VALUES "
                "(1, 'main_bot', '2026-10-20 09:00', NULL, '2026-10-20 09:00'), "
                "(2, 'main_bot', '2026-10-21 10:00', '2026-10-25 12:00', '2026-10-25 12:00')"
            )
        )
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT user_id, day::text, touchpoint, event FROM audience_days ORDER BY 1, 2, 3, 4")
        ).all()
    assert [tuple(row) for row in rows] == [
        (1, "2026-10-20", "mini_app", "visit"),
        (1, "2026-11-01", "mini_app", "visit"),
        (2, "2026-10-21", "main_bot", "visit"),
        (2, "2026-10-25", "main_bot", "block"),
    ]


def test_it_downgrades_cleanly_and_leaves_the_audience(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), BEFORE)
    with database.connect() as conn:
        assert not sa.inspect(conn).has_table("audience_days")
        assert sa.inspect(conn).has_table("audience_touches")
