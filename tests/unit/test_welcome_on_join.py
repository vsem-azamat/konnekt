"""Welcome messages, which the repository has advertised without sending.

`Chat.welcome_message`, `is_welcome_enabled` and `time_delete` have been stored,
exposed in the admin UI and named in the docs since the aiogram 2 to 3 move,
while nothing read them at join time. These tests are what makes the toggle
mean something.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, User
from app.db.models import Chat as DbChat
from app.presentation.telegram.handlers.events import user_joined
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001234
USER_ID = 4242


def _join() -> ChatMemberUpdated:
    """A join. Which transitions reach the handler is aiogram's filter, not ours."""
    user = User(id=USER_ID, is_bot=False, first_name="Newcomer")
    new_member = ChatMemberMember(user=user, status=ChatMemberStatus.MEMBER)
    return ChatMemberUpdated(
        chat=Chat(id=CHAT_ID, type="supergroup", title="Managed"),
        from_user=user,
        date=datetime.now(UTC),
        old_chat_member=ChatMemberLeft(user=user, status=ChatMemberStatus.LEFT),
        new_chat_member=new_member,
    )


async def _seed(session: AsyncSession, **kwargs) -> DbChat:
    chat = DbChat(id=CHAT_ID, title="Managed", resource_status=DbChat.STATUS_APPROVED, **kwargs)
    session.add(chat)
    await session.commit()
    return chat


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.send_message = AsyncMock(return_value=MagicMock(message_id=9))
    return tg_bot


async def test_enabled_welcome_is_sent(session: AsyncSession, bot) -> None:
    await _seed(session, welcome_message="Добро пожаловать!", is_welcome_enabled=True)

    await user_joined(_join(), bot, session)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == CHAT_ID
    assert "Добро пожаловать!" in bot.send_message.await_args.kwargs["text"]


async def test_disabled_welcome_stays_silent(session: AsyncSession, bot) -> None:
    await _seed(session, welcome_message="Добро пожаловать!", is_welcome_enabled=False)

    await user_joined(_join(), bot, session)

    bot.send_message.assert_not_awaited()


async def test_enabled_but_empty_welcome_stays_silent(session: AsyncSession, bot) -> None:
    """An enabled toggle with nothing to say must not post an empty message."""
    await _seed(session, is_welcome_enabled=True)

    await user_joined(_join(), bot, session)

    bot.send_message.assert_not_awaited()


async def test_unknown_chat_stays_silent(session: AsyncSession, bot) -> None:
    await user_joined(_join(), bot, session)

    bot.send_message.assert_not_awaited()


async def test_configured_lifetime_schedules_the_deletion(session: AsyncSession, bot, monkeypatch) -> None:
    """time_delete has been stored and ignored; it now governs the cleanup."""
    scheduled: list[int] = []
    monkeypatch.setattr(
        "app.presentation.telegram.handlers.events.sleep_and_delete",
        lambda _message, seconds: scheduled.append(seconds),
    )
    await _seed(session, welcome_message="Привет", is_welcome_enabled=True, time_delete=45)

    await user_joined(_join(), bot, session)

    assert scheduled == [45]


async def test_zero_lifetime_keeps_the_message(session: AsyncSession, bot, monkeypatch) -> None:
    scheduled: list[int] = []
    monkeypatch.setattr(
        "app.presentation.telegram.handlers.events.sleep_and_delete",
        lambda _message, seconds: scheduled.append(seconds),
    )
    await _seed(session, welcome_message="Привет", is_welcome_enabled=True, time_delete=0)

    await user_joined(_join(), bot, session)

    assert scheduled == []


async def test_a_greeting_telegram_refuses_does_not_break_the_join(session: AsyncSession, bot) -> None:
    """One bad stored value used to fail every join in the chat."""
    from aiogram.exceptions import TelegramBadRequest

    await _seed(session, welcome_message="Привет <b>", is_welcome_enabled=True)
    bot.send_message.side_effect = TelegramBadRequest(method=MagicMock(), message="can't parse entities")

    await user_joined(_join(), bot, session)
