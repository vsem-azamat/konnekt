"""Migration b3f8d1c6e925 against the databases it actually meets.

Production already carried a CHECK named ``ck_chats_resource_status`` with the
three old values, created by hand before the migrations were squashed, and the
first deploy of the migration failed on it. So both shapes are run: a database
that has the old constraint and one that has none.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.core.config import settings

pytestmark = pytest.mark.integration

BEFORE = "a9c4e2d7f610"
THIS = "b3f8d1c6e925"
OLD_CHECK = "resource_status IN ('discovered', 'approved', 'disabled')"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database(pg_container, monkeypatch):
    """A database of its own, named in settings so alembic's env.py finds it."""
    name = f"mig_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(pg_container.get_connection_url().replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.engine.make_url(pg_container.get_connection_url())
    for field, value in {
        "user": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "name": name,
    }.items():
        monkeypatch.setattr(settings.database, field, value)
    engine = sa.create_engine(settings.database.sync_url)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _alembic() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def _check(engine: sa.Engine) -> str | None:
    with engine.connect() as conn:
        return conn.scalar(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_chats_resource_status' AND conrelid = 'chats'::regclass"
            )
        )


def _chat(engine: sa.Engine, chat_id: int, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO chats (id, title, resource_status, is_forum, time_delete, is_welcome_enabled, "
                "is_captcha_enabled, is_service_cleanup_enabled, created_at, modified_at) "
                "VALUES (:id, 't', :status, false, 60, false, false, true, now(), now())"
            ),
            {"id": chat_id, "status": status},
        )


@pytest.mark.parametrize("old_check", [True, False], ids=["as-in-production", "without-a-check"])
def test_upgrade_and_downgrade_meet_either_database(database, old_check: bool) -> None:
    config = _alembic()
    command.upgrade(config, BEFORE)
    if old_check:
        with database.begin() as conn:
            conn.execute(sa.text(f"ALTER TABLE chats ADD CONSTRAINT ck_chats_resource_status CHECK ({OLD_CHECK})"))
    _chat(database, -1, "approved")

    command.upgrade(config, THIS)

    assert "observed" in (_check(database) or "")
    _chat(database, -2, "observed")
    with pytest.raises(sa.exc.IntegrityError):
        _chat(database, -3, "bogus")

    command.downgrade(config, BEFORE)

    # Back to what production had: the three old values, the watched chat
    # disabled rather than left on a value the old release cannot read.
    restored = _check(database) or ""
    assert "approved" in restored
    assert "observed" not in restored
    with database.connect() as conn:
        assert conn.scalar(sa.text("SELECT resource_status FROM chats WHERE id = -2")) == "disabled"

    command.upgrade(config, THIS)
    assert "observed" in (_check(database) or "")
