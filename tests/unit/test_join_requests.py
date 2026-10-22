"""Join requests: turn blacklisted people away at the door.

Until now the blacklist was only enforced once someone was already inside — and
after the middleware fix, only at the moment they joined. A chat that requires
approval never reaches that moment, so the request itself has to be answered.

Nobody is approved here unless the chat lets everyone in: deciding who gets in
is otherwise the operator's call or the captcha's; this only removes the
people they have already decided about.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import ApproveChatJoinRequest
from aiogram.types import Chat, ChatJoinRequest, User
from app.core.config import settings
from app.db.models import Chat as DbChat
from app.db.models import JoinCheck
from app.db.models import User as DbUser
from app.presentation.telegram.handlers.events import join_requested
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001234
USER_ID = 4242


def _request(query_id: str | None = None) -> ChatJoinRequest:
    user = User(id=USER_ID, is_bot=False, first_name="Applicant")
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="Managed"),
        from_user=user,
        user_chat_id=USER_ID,
        date=datetime.now(UTC),
        query_id=query_id,
    )


async def _seed_chat(session: AsyncSession) -> None:
    session.add(DbChat(id=CHAT_ID, title="Managed", resource_status=DbChat.STATUS_APPROVED))
    await session.commit()


async def _blacklist(session: AsyncSession) -> None:
    user = DbUser(id=USER_ID, username="spammer")
    user.blocked = True
    session.add(user)
    await session.commit()


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.decline_chat_join_request = AsyncMock()
    tg_bot.approve_chat_join_request = AsyncMock()
    tg_bot.answer_chat_join_request_query = AsyncMock()
    tg_bot.send_chat_join_request_web_app = AsyncMock()
    tg_bot.send_message = AsyncMock()
    return tg_bot


async def test_blacklisted_applicant_is_declined(session: AsyncSession, bot) -> None:
    await _seed_chat(session)
    await _blacklist(session)

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.approve_chat_join_request.assert_not_awaited()


async def test_ordinary_applicant_is_left_to_the_admins(session: AsyncSession, bot) -> None:
    """Approving is the operator's decision; the bot does not make it for them."""
    await _seed_chat(session)

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_not_awaited()
    bot.approve_chat_join_request.assert_not_awaited()


async def test_blacklisted_applicant_declined_through_the_query(session: AsyncSession, bot) -> None:
    """When acting as the chat's guard bot the answer goes back on the query."""
    await _seed_chat(session)
    await _blacklist(session)

    await join_requested(_request(query_id="q-1"), bot, session)

    bot.answer_chat_join_request_query.assert_awaited_once_with(chat_join_request_query_id="q-1", result="decline")
    bot.decline_chat_join_request.assert_not_awaited()


async def test_guarded_request_from_a_stranger_goes_to_the_admins(session: AsyncSession, bot) -> None:
    """A guard bot must answer, or the request hangs — 'queue' hands it over.

    There is no check to run yet, so passing it to the humans is the honest
    answer rather than approving on their behalf.
    """
    await _seed_chat(session)

    await join_requested(_request(query_id="q-2"), bot, session)

    bot.answer_chat_join_request_query.assert_awaited_once_with(chat_join_request_query_id="q-2", result="queue")


async def test_unknown_chat_is_left_alone(session: AsyncSession, bot) -> None:
    await _blacklist(session)

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_not_awaited()
    bot.answer_chat_join_request_query.assert_not_awaited()


async def _seed_chat_with_check(session: AsyncSession) -> None:
    session.add(
        DbChat(
            id=CHAT_ID,
            title="Guarded",
            resource_status=DbChat.STATUS_APPROVED,
            join_mode=DbChat.JOIN_CAPTCHA,
        )
    )
    await session.commit()


async def test_check_is_offered_instead_of_queueing(session: AsyncSession, bot, monkeypatch) -> None:
    monkeypatch.setattr(settings.webapi, "public_url", "https://example.test/")

    await _seed_chat_with_check(session)

    await join_requested(_request(query_id="q-3"), bot, session)

    bot.send_chat_join_request_web_app.assert_awaited_once()
    assert bot.send_chat_join_request_web_app.await_args.kwargs["web_app_url"] == "https://example.test/join?q=q-3"
    bot.answer_chat_join_request_query.assert_not_awaited()


async def test_the_pending_check_is_bound_to_the_applicant(session: AsyncSession, bot, monkeypatch) -> None:
    """Stored, not carried in the URL — a query id alone must not let anyone in."""
    monkeypatch.setattr(settings.webapi, "public_url", "https://example.test")
    await _seed_chat_with_check(session)

    await join_requested(_request(query_id="q-4"), bot, session)

    stored = await session.scalar(select(JoinCheck).where(JoinCheck.query_id == "q-4"))
    assert stored is not None
    assert stored.user_id == USER_ID
    assert stored.chat_id == CHAT_ID
    assert stored.passed_at is None


async def test_without_a_public_url_the_request_still_gets_an_answer(session: AsyncSession, bot, monkeypatch) -> None:
    """A half-configured deployment must not leave the applicant hanging."""
    monkeypatch.setattr(settings.webapi, "public_url", "")
    await _seed_chat_with_check(session)

    await join_requested(_request(query_id="q-5"), bot, session)

    bot.send_chat_join_request_web_app.assert_not_awaited()
    bot.answer_chat_join_request_query.assert_awaited_once_with(chat_join_request_query_id="q-5", result="queue")


async def test_a_blacklisted_applicant_is_never_offered_the_check(session: AsyncSession, bot, monkeypatch) -> None:
    monkeypatch.setattr(settings.webapi, "public_url", "https://example.test")
    await _seed_chat_with_check(session)
    await _blacklist(session)

    await join_requested(_request(query_id="q-6"), bot, session)

    bot.send_chat_join_request_web_app.assert_not_awaited()
    bot.answer_chat_join_request_query.assert_awaited_once_with(chat_join_request_query_id="q-6", result="decline")


# --- a chat that lets everyone in --------------------------------------------


async def _seed_open_chat(session: AsyncSession) -> None:
    session.add(DbChat(id=CHAT_ID, title="Open", resource_status=DbChat.STATUS_APPROVED, join_mode=DbChat.JOIN_OPEN))
    await session.commit()


async def test_an_open_chat_approves_the_request_at_once(session: AsyncSession, bot) -> None:
    await _seed_open_chat(session)

    await join_requested(_request(), bot, session)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.send_message.assert_not_called()


async def test_an_open_chat_still_turns_the_blacklisted_away(session: AsyncSession, bot) -> None:
    await _seed_open_chat(session)
    await _blacklist(session)

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    bot.approve_chat_join_request.assert_not_awaited()


async def test_an_open_chat_approves_through_the_query_as_guard_bot(session: AsyncSession, bot) -> None:
    await _seed_open_chat(session)

    await join_requested(_request(query_id="q-7"), bot, session)

    bot.answer_chat_join_request_query.assert_awaited_once_with(chat_join_request_query_id="q-7", result="approve")
    bot.approve_chat_join_request.assert_not_awaited()


async def test_an_approval_telegram_refuses_leaves_the_request_to_the_admins(session: AsyncSession, bot) -> None:
    await _seed_open_chat(session)
    bot.approve_chat_join_request.side_effect = TelegramBadRequest(
        method=ApproveChatJoinRequest(chat_id=CHAT_ID, user_id=USER_ID), message="Bad Request: CHAT_ADMIN_REQUIRED"
    )

    await join_requested(_request(), bot, session)

    bot.decline_chat_join_request.assert_not_awaited()
