"""The approval gate must cover joins, not just messages.

Public moderation actions run only for chats with status `approved` — see the
approval invariant in `docs/invariants.md`. Once blacklist enforcement moved
onto `dp.chat_member`, a gate that only understood `Update.message` let a ban
fire in a chat the operator had never approved.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import types
from aiogram.enums import ChatMemberStatus
from aiogram.types import (
    Chat,
    ChatJoinRequest,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    TelegramObject,
    Update,
    User,
)
from app.db.models import Chat as DbChat
from app.presentation.telegram.middlewares.managed_chats import ApprovedChatGateMiddleware

from tests.telegram_helpers import create_test_chat

pytestmark = pytest.mark.middleware


class _Handler:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, event: TelegramObject, data: dict[str, Any]) -> None:
        self.called = True


def _join_update(chat: Chat) -> Update:
    user = User(id=4242, is_bot=False, first_name="Joiner")
    return Update(
        update_id=1,
        chat_member=ChatMemberUpdated(
            chat=chat,
            from_user=user,
            date=datetime.now(UTC),
            old_chat_member=ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT),
            new_chat_member=ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER),
        ),
    )


async def test_join_in_unapproved_chat_is_stopped() -> None:
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, _join_update(create_test_chat()), {"chat_resource_status": DbChat.STATUS_DISCOVERED})

    assert handler.called is False


async def test_join_in_approved_chat_passes() -> None:
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, _join_update(create_test_chat()), {"chat_is_approved": True})

    assert handler.called is True


async def test_private_chat_events_are_not_gated() -> None:
    """The gate is about group resources; private updates must flow."""
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()
    private = Chat(id=7, type="private")

    await gate(handler, _join_update(private), {})

    assert handler.called is True


async def test_non_update_objects_pass_through() -> None:
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, types.TelegramObject(), {})

    assert handler.called is True


def _join_request_update(chat: Chat) -> Update:
    user = User(id=4242, is_bot=False, first_name="Applicant")
    return Update(
        update_id=2,
        chat_join_request=ChatJoinRequest(
            chat=chat,
            from_user=user,
            user_chat_id=user.id,
            date=datetime.now(UTC),
        ),
    )


async def test_join_request_in_unapproved_chat_is_stopped() -> None:
    """Turning an applicant away is visible to them, so approval governs it."""
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, _join_request_update(create_test_chat()), {"chat_resource_status": DbChat.STATUS_DISCOVERED})

    assert handler.called is False


async def test_join_request_in_approved_chat_passes() -> None:
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, _join_request_update(create_test_chat()), {"chat_is_approved": True})

    assert handler.called is True


async def test_the_bots_own_membership_in_an_unapproved_group_is_stopped() -> None:
    """my_chat_member is polled for private blocks; in a group it must meet the same gate."""
    update = _join_update(create_test_chat())
    own = Update(update_id=2, my_chat_member=update.chat_member)
    gate = ApprovedChatGateMiddleware()
    handler = _Handler()

    await gate(handler, own, {"chat_resource_status": DbChat.STATUS_DISCOVERED})

    assert handler.called is False
