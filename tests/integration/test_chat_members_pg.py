"""Chat members and the users' language, on PostgreSQL: concurrent first updates and the migration."""

from __future__ import annotations

import asyncio
import datetime

import pytest
import sqlalchemy as sa
from aiogram.types import ChatMemberLeft, ChatMemberMember, User
from alembic import command
from app.chats import members
from app.db.models import ChatMember
from app.db.models import User as DbUser
from app.moderation import history_service

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

CHAT_ID = -1001370017010
JAN = User(id=60606, is_bot=False, first_name="Jan", language_code="cs")
T0 = datetime.datetime(2026, 10, 29, 12, 0)


async def test_a_join_and_a_leave_at_once_keep_the_newer(pg_session_maker) -> None:
    async def one(member, at) -> None:
        async with pg_session_maker() as session:
            await members.record(session, CHAT_ID, member, at=at)

    await asyncio.gather(
        one(ChatMemberMember(user=JAN), T0), one(ChatMemberLeft(user=JAN), T0 + datetime.timedelta(seconds=1))
    )

    async with pg_session_maker() as session:
        row = await session.get(ChatMember, (CHAT_ID, JAN.id))
    assert row is not None
    assert row.status == "left"


async def test_the_language_is_kept_when_left_out(pg_session) -> None:
    await history_service.merge_user(pg_session, JAN)
    await history_service.merge_user(pg_session, User(id=JAN.id, is_bot=False, first_name="Jan"))

    row = await pg_session.get(DbUser, JAN.id)
    await pg_session.refresh(row)
    assert (row.language_code, row.is_premium) == ("cs", False)


def test_it_upgrades_and_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    command.downgrade(_alembic(), "-1")
    with database.connect() as conn:
        inspector = sa.inspect(conn)
        assert not inspector.has_table("chat_members")
        assert "language_code" not in {column["name"] for column in inspector.get_columns("users")}
