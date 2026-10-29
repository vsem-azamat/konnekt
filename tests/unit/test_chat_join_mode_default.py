"""A chat the bot first meets gets the join mode it was already acting in.

Before modes, a chat without the captcha left Telegram's own requests to the
admins and gave out a bot link that asked for none. So a public chat starts
with ADMINS and a private one with OPEN: a private chat on ADMINS would get a
link that asks for a request nobody answers.
"""

import pytest
from app.db.models import Chat
from app.db.repositories.chat import ChatRepository
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("public", "mode"), [(True, Chat.JOIN_ADMINS), (False, Chat.JOIN_OPEN)])
async def test_a_new_chat_starts_in_the_mode_it_was_already_in(session: AsyncSession, public: bool, mode: str) -> None:
    await ChatRepository(session).merge_chat(-100, title="New", is_public=public)

    chat = await session.get(Chat, -100)
    assert chat is not None
    assert chat.join_mode == mode


async def test_a_known_chat_keeps_its_mode(session: AsyncSession) -> None:
    session.add(Chat(id=-100, title="Known", join_mode=Chat.JOIN_CAPTCHA))
    await session.commit()

    await ChatRepository(session).merge_chat(-100, title="Renamed", is_public=False)

    chat = await session.get(Chat, -100)
    assert chat is not None
    await session.refresh(chat)
    assert chat.join_mode == Chat.JOIN_CAPTCHA
    assert chat.title == "Renamed"


async def test_the_old_column_follows_the_mode_for_a_rollback(session: AsyncSession) -> None:
    chat = Chat(id=-100, title="Known", join_mode=Chat.JOIN_CAPTCHA)
    assert chat._legacy_captcha is True
    chat.join_mode = Chat.JOIN_OPEN
    assert chat._legacy_captcha is False
