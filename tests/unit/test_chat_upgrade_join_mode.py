"""A group upgraded to a supergroup takes its captcha along, and only that.

The other modes depend on whether the chat is public, which an upgrade often
changes: a private OPEN group made public would let everyone in where the
admins used to decide.
"""

import pytest
from app.chats.migration import follow_upgrade
from app.db.models import Chat
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

OLD, NEW = -100, -1001


async def _upgrade(session: AsyncSession, old_mode: str, *, new: Chat | None = None) -> Chat:
    session.add(Chat(id=OLD, title="Group", resource_status=Chat.STATUS_APPROVED, join_mode=old_mode))
    if new is not None:
        session.add(new)
    await session.commit()

    assert await follow_upgrade(session, old_id=OLD, new_id=NEW)

    upgraded = await session.get(Chat, NEW)
    assert upgraded is not None
    return upgraded


@pytest.mark.parametrize("already_decided", [False, True])
async def test_the_captcha_goes_along(session: AsyncSession, already_decided: bool) -> None:
    status = Chat.STATUS_APPROVED if already_decided else Chat.STATUS_DISCOVERED
    new = Chat(id=NEW, title="Supergroup", resource_status=status, join_mode=Chat.JOIN_OPEN)

    upgraded = await _upgrade(session, Chat.JOIN_CAPTCHA, new=new)

    assert upgraded.join_mode == Chat.JOIN_CAPTCHA


async def test_letting_everyone_in_does_not(session: AsyncSession) -> None:
    new = Chat(id=NEW, title="Supergroup", resource_status=Chat.STATUS_DISCOVERED, join_mode=Chat.JOIN_ADMINS)

    upgraded = await _upgrade(session, Chat.JOIN_OPEN, new=new)

    assert upgraded.join_mode == Chat.JOIN_ADMINS
