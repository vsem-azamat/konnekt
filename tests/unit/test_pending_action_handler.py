"""Button presses on a proposed destructive action.

The handler sits on the moderator dispatcher because the moderator bot sent the
message; Telegram returns a press to the sending identity.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import types
from app.core.config import settings
from app.core.enums import PendingActionStatus
from app.core.time import utc_now
from app.db.models import PendingAction
from app.presentation.telegram.handlers.pending_actions import handle_pending_action
from app.presentation.telegram.utils.callback_data import PendingActionDecision
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

ADMIN_ID = 555
OUTSIDER_ID = 111
TARGET_ID = 999


@pytest.fixture(autouse=True)
def _super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.admin, "super_admins", [ADMIN_ID])


def _callback(user_id: int = ADMIN_ID) -> AsyncMock:
    message = AsyncMock(spec=types.Message)
    message.chat = SimpleNamespace(id=ADMIN_ID)
    message.text = "Запрошено действие: забанить"
    message.message_id = 42
    message.edit_text = AsyncMock()
    callback = AsyncMock()
    callback.message = message
    callback.from_user = SimpleNamespace(id=user_id)
    return callback


async def _seed(session: AsyncSession, *, minutes: int = 30) -> PendingAction:
    pending = PendingAction(
        origin="mcp",
        initiator_id=ADMIN_ID,
        action="ban",
        target_user_id=TARGET_ID,
        expires_at=utc_now() + datetime.timedelta(minutes=minutes),
        chat_id=-1001,
    )
    session.add(pending)
    await session.commit()
    await session.refresh(pending)
    return pending


async def test_non_super_admin_cannot_press(session: AsyncSession) -> None:
    pending = await _seed(session)
    callback = _callback(user_id=OUTSIDER_ID)

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=1), AsyncMock(), session)

    callback.answer.assert_awaited_with("Только для супер-админов", show_alert=True)
    await session.refresh(pending)
    assert pending.status == PendingActionStatus.PENDING


async def test_reject_records_and_executes_nothing(session: AsyncSession) -> None:
    pending = await _seed(session)
    bot = AsyncMock()
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=0), bot, session)

    await session.refresh(pending)
    assert pending.status == PendingActionStatus.REJECTED
    assert pending.resolved_by == ADMIN_ID
    bot.ban_chat_member.assert_not_awaited()
    callback.message.edit_text.assert_awaited_once()


async def test_confirm_bans_the_target(session: AsyncSession) -> None:
    pending = await _seed(session)
    bot = AsyncMock()
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=1), bot, session)

    await session.refresh(pending)
    assert pending.status == PendingActionStatus.CONFIRMED
    bot.ban_chat_member.assert_awaited_once()


async def test_expired_proposal_is_refused_at_the_press(session: AsyncSession) -> None:
    pending = await _seed(session, minutes=-1)
    bot = AsyncMock()
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=1), bot, session)

    bot.ban_chat_member.assert_not_awaited()
    callback.answer.assert_awaited_with("Запрос уже обработан или истёк")
    await session.refresh(pending)
    assert pending.status == PendingActionStatus.EXPIRED


async def test_unknown_id_says_so_without_raising(session: AsyncSession) -> None:
    bot = AsyncMock()
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=424242, confirm=1), bot, session)

    bot.ban_chat_member.assert_not_awaited()
    callback.answer.assert_awaited_with("Запрос уже обработан или истёк")


async def test_a_refused_blacklist_says_why(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    pending = await _seed(session)
    pending.action = "blacklist"
    await session.commit()
    monkeypatch.setattr(settings.admin, "super_admins", [ADMIN_ID, TARGET_ID])
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=1), AsyncMock(), session)

    assert "главн" in callback.answer.await_args.args[0].lower()
    assert "главн" in callback.message.edit_text.await_args.args[0].lower()


async def test_a_refused_ban_is_shown_to_the_admin(session: AsyncSession) -> None:
    """Any error escaped the handler: no answer, and the buttons stayed as if nothing was pressed."""
    pending = await _seed(session)
    bot = AsyncMock()
    bot.ban_chat_member.side_effect = RuntimeError("Bad Request: not enough rights")
    callback = _callback()

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=1), bot, session)

    assert callback.answer.await_args.kwargs.get("show_alert") is True
    assert "Не выполнено" in callback.answer.await_args.args[0]
    await session.refresh(pending)
    assert pending.status == PendingActionStatus.FAILED


async def test_the_reason_stays_text_after_the_press(session: AsyncSession) -> None:
    """Re-sent from message.text, an escaped reason became live HTML, or broke the edit."""
    pending = await _seed(session)
    callback = _callback()
    callback.message.text = "Причина: spam <3 <a href='https://evil'>x</a>"
    callback.message.html_text = "Причина: spam &lt;3 &lt;a href='https://evil'&gt;x&lt;/a&gt;"

    await handle_pending_action(callback, PendingActionDecision(pending_id=pending.id, confirm=0), AsyncMock(), session)

    sent = callback.message.edit_text.await_args.args[0]
    assert sent.startswith("Причина: spam &lt;3 &lt;a href=")
