"""The bot's rights and their history, on PostgreSQL: the migration and the locked write.

SQLite ignores `FOR UPDATE` and stores JSON as text; this pins that PostgreSQL
takes the same writes and gives the rights back as they went in.
"""

from __future__ import annotations

import datetime

import pytest
import sqlalchemy as sa
from aiogram.types import ChatMemberAdministrator, ChatMemberLeft, User
from alembic import command
from app.chats import bot_rights
from app.db.models import ChatBotRights, ChatBotRightsChange
from sqlalchemy import select

from tests.integration.test_chat_status_migration import _alembic, database  # noqa: F401

pytestmark = pytest.mark.integration

CHAT_ID = -1001370017010
BOT = User(id=42, is_bot=True, first_name="Konnekt")
T0 = datetime.datetime(2026, 10, 29, 12, 0)
ADMIN = ChatMemberAdministrator.model_validate(
    {
        "user": BOT,
        "can_be_edited": False,
        "is_anonymous": False,
        "can_manage_chat": True,
        "can_delete_messages": True,
        "can_manage_video_chats": True,
        "can_restrict_members": True,
        "can_promote_members": False,
        "can_change_info": True,
        "can_invite_users": True,
        "can_post_stories": False,
        "can_edit_stories": False,
        "can_delete_stories": False,
        "can_send_welcome_messages": False,
    }
)


async def test_a_change_and_its_history_round_trip(pg_session) -> None:
    await bot_rights.record(pg_session, CHAT_ID, ADMIN, at=T0, by=7)
    await bot_rights.record(pg_session, CHAT_ID, ChatMemberLeft(user=BOT), at=T0 + datetime.timedelta(minutes=1))

    row = await pg_session.get(ChatBotRights, CHAT_ID)
    assert row is not None
    assert row.status == "left"
    changes = (await pg_session.scalars(select(ChatBotRightsChange).order_by(ChatBotRightsChange.id))).all()
    assert [c.status for c in changes] == ["administrator", "left"]
    assert changes[0].rights["can_restrict_members"] is True


def test_it_upgrades_and_downgrades_cleanly(database) -> None:  # noqa: F811
    command.upgrade(_alembic(), "head")
    with database.connect() as conn:
        assert sa.inspect(conn).has_table("chat_bot_rights")
        assert sa.inspect(conn).has_table("chat_bot_rights_changes")
    command.downgrade(_alembic(), "b6e1f4a8c203")
    with database.connect() as conn:
        assert not sa.inspect(conn).has_table("chat_bot_rights")
        assert not sa.inspect(conn).has_table("chat_bot_rights_changes")
