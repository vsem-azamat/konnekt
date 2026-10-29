"""What getChat says about a chat lands in its row through one writer.

The title, the join setting and the photo used to be copied by three callers
in three ways, and the rest of the answer (username, description, slow mode,
default permissions) was thrown away.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import ChatFullInfo
from app.chats import profile
from app.chats.metadata import _metadata_of
from app.db.models import Chat

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010


def _info(**overrides) -> ChatFullInfo:
    return ChatFullInfo.model_validate(
        {
            "id": CHAT_ID,
            "type": "supergroup",
            "title": "ČVUT FIT",
            "username": "cvut_fit",
            "description": "Чат студентов FIT",
            "is_forum": True,
            "join_by_request": True,
            "slow_mode_delay": 30,
            "permissions": {"can_send_messages": True, "can_invite_users": False},
            "has_protected_content": True,
            "has_hidden_members": True,
            "has_aggressive_anti_spam_enabled": True,
            "message_auto_delete_time": 86400,
            "linked_chat_id": -1009,
            "accent_color_id": 0,
            "max_reaction_count": 11,
            "accepted_gift_types": {
                "unlimited_gifts": False,
                "limited_gifts": False,
                "unique_gifts": False,
                "premium_subscription": False,
                "gifts_from_channels": False,
            },
            **overrides,
        }
    )


async def test_everything_telegram_said_is_kept(session) -> None:
    chat = Chat(id=CHAT_ID, title="Старое имя")
    session.add(chat)

    await profile.apply(session=session, bot=AsyncMock(), chat=chat, metadata=_metadata_of(_info()))

    assert (chat.title, chat.username, chat.description, chat.chat_type) == (
        "ČVUT FIT",
        "cvut_fit",
        "Чат студентов FIT",
        "supergroup",
    )
    assert (chat.is_forum, chat.join_by_request, chat.slow_mode_delay) == (True, True, 30)
    assert chat.permissions == {"can_send_messages": True, "can_invite_users": False}
    assert (chat.has_protected_content, chat.has_hidden_members, chat.has_aggressive_anti_spam_enabled) == (
        True,
        True,
        True,
    )
    assert (chat.message_auto_delete_time, chat.linked_chat_id) == (86400, -1009)


async def test_a_setting_switched_off_is_recorded_as_off(session) -> None:
    """Telegram leaves a flag out when it is off: the answer without it is off, not unknown."""
    chat = Chat(id=CHAT_ID, title="ČVUT FIT")
    chat.has_protected_content, chat.slow_mode_delay, chat.username = True, 30, "cvut_fit"
    session.add(chat)

    info = _info(has_protected_content=None, slow_mode_delay=None, username=None, is_forum=None)
    await profile.apply(session=session, bot=AsyncMock(), chat=chat, metadata=_metadata_of(info))

    assert (chat.has_protected_content, chat.slow_mode_delay, chat.username, chat.is_forum) == (
        False,
        None,
        None,
        False,
    )


async def test_anti_spam_left_out_is_unknown_not_off(session) -> None:
    """Telegram tells only an administrator; a bot removed or demoted would otherwise record it as off."""
    chat = Chat(id=CHAT_ID, title="ČVUT FIT")
    chat.has_aggressive_anti_spam_enabled = True
    session.add(chat)

    info = _info(has_aggressive_anti_spam_enabled=None)
    await profile.apply(session=session, bot=AsyncMock(), chat=chat, metadata=_metadata_of(info))

    assert chat.has_aggressive_anti_spam_enabled is None


async def test_an_empty_title_and_the_admins_settings_are_left_alone(session) -> None:
    chat = Chat(id=CHAT_ID, title="ČVUT FIT", welcome_message="Ahoj", join_mode=Chat.JOIN_CAPTCHA)
    session.add(chat)

    await profile.apply(session=session, bot=AsyncMock(), chat=chat, metadata=_metadata_of(_info(title=None)))

    assert (chat.title, chat.welcome_message, chat.join_mode) == ("ČVUT FIT", "Ahoj", Chat.JOIN_CAPTCHA)
