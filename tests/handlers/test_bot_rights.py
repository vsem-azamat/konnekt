"""A bot that regains the invite right mends its listed chats' links at once."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatInviteLink, ChatMemberAdministrator, ChatMemberMember, User
from app.db.models import Chat
from app.presentation.telegram.handlers.events import bot_rights_changed

from tests.telegram_helpers import TelegramObjectFactory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

BOT = User(id=1, is_bot=True, first_name="bot")
CHAT_ID = -1001234567890


def _admin(*, invite: bool) -> ChatMemberAdministrator:
    flags: dict[str, bool] = dict.fromkeys(
        (
            "can_be_edited",
            "is_anonymous",
            "can_manage_chat",
            "can_delete_messages",
            "can_manage_video_chats",
            "can_restrict_members",
            "can_promote_members",
            "can_change_info",
            "can_post_stories",
            "can_edit_stories",
            "can_delete_stories",
            "can_send_welcome_messages",
        ),
        False,
    )
    return ChatMemberAdministrator(user=BOT, status=ChatMemberStatus.ADMINISTRATOR, can_invite_users=invite, **flags)  # ty: ignore[invalid-argument-type]


def _event(old, new):
    return TelegramObjectFactory.create_chat_member_updated(
        chat=TelegramObjectFactory.create_chat(id=CHAT_ID, type="supergroup"),
        user=BOT,
        old_chat_member=old,
        new_chat_member=new,
    )


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.get_chat = AsyncMock(return_value=MagicMock(username=None, join_by_request=False))
    bot.edit_chat_invite_link = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="INVITE_REVOKED_MISSING")
    )
    bot.create_chat_invite_link = AsyncMock(
        return_value=ChatInviteLink(
            invite_link="https://t.me/+fresh",
            creator=BOT,
            creates_join_request=False,
            is_primary=False,
            is_revoked=False,
        )
    )
    return bot


async def _listed(session: AsyncSession, **fields) -> None:
    session.add(Chat(id=CHAT_ID, title="room", resource_status=fields.pop("status", Chat.STATUS_APPROVED), **fields))
    await session.commit()


async def test_getting_the_invite_right_back_replaces_a_dead_link(session: AsyncSession) -> None:
    await _listed(session, public_link="https://t.me/+dead")
    bot = _bot()

    await bot_rights_changed(
        _event(ChatMemberMember(user=BOT, status=ChatMemberStatus.MEMBER), _admin(invite=True)), bot, session
    )

    chat = await session.get(Chat, CHAT_ID)
    assert chat is not None
    assert chat.public_link == "https://t.me/+fresh"


async def test_losing_the_right_does_nothing_here(session: AsyncSession) -> None:
    await _listed(session, public_link="https://t.me/+dead")
    bot = _bot()

    await bot_rights_changed(_event(_admin(invite=True), _admin(invite=False)), bot, session)

    bot.get_chat.assert_not_called()


async def test_a_chat_that_is_not_listed_is_not_given_a_link(session: AsyncSession) -> None:
    await _listed(session, public_link=None)
    bot = _bot()

    await bot_rights_changed(
        _event(ChatMemberMember(user=BOT, status=ChatMemberStatus.MEMBER), _admin(invite=True)), bot, session
    )

    bot.create_chat_invite_link.assert_not_called()


async def test_other_rights_changes_are_ignored(session: AsyncSession) -> None:
    await _listed(session, public_link="https://t.me/+dead")
    bot = _bot()

    await bot_rights_changed(_event(_admin(invite=True), _admin(invite=True)), bot, session)

    bot.get_chat.assert_not_called()
