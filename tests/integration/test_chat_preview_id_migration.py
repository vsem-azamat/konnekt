"""A chat known only by its invite link, on PostgreSQL: listed as somebody else's, never moderated."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from app.db.models import Chat
from sqlalchemy.exc import IntegrityError

from tests.integration.test_chat_kind_migration import _insert
from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

PREVIEW = Chat.preview_id_for("5byLmmR3YvIyYWFi")


@pytest.mark.parametrize("status", ["external", "disabled"])
def test_it_may_be_listed_or_taken_down(database, status) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        _insert(conn, id=PREVIEW, status=status)


@pytest.mark.parametrize("status", ["approved", "observed", "discovered"])
def test_it_is_never_moderated(database, status) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with pytest.raises(IntegrityError), database.begin() as conn:
        _insert(conn, id=PREVIEW, status=status)


def test_telegram_s_own_ids_are_untouched(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.begin() as conn:
        _insert(conn, id=-(2**52) + 1, status="approved")


def test_it_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "dc297231ecfd")
    with database.begin() as conn:
        _insert(conn, id=PREVIEW, status="approved")
    with database.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM chats")).scalar_one() == 1
