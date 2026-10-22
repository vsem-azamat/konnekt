"""Button presses on the captcha and on a wave alert.

The applicant's tap goes to the service with the presser's own id, so a
forwarded captcha does nothing for anyone else. A wave is decided by a super
admin only: declining hundreds of requests is not a button for whoever is in
the report chat.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import service, waves
from app.captcha.challenge import EMOJI, CaptchaPick
from app.captcha.waves import WaveDecision
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha, JoinWave
from app.presentation.telegram.handlers.captcha import captcha_pick, wave_decision
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
USER_ID = 4242
ADMIN_ID = 555
OUTSIDER_ID = 111


@pytest.fixture(autouse=True)
def _super_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.admin, "super_admins", [ADMIN_ID])


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    sent = MagicMock()
    sent.message_id = 77
    tg_bot.send_message = AsyncMock(return_value=sent)
    tg_bot.edit_message_text = AsyncMock()
    tg_bot.approve_chat_join_request = AsyncMock()
    tg_bot.decline_chat_join_request = AsyncMock()
    return tg_bot


@pytest.fixture
async def chat(session: AsyncSession) -> DbChat:
    row = DbChat(id=CHAT_ID, title="ČVUT FIT", resource_status=DbChat.STATUS_APPROVED, join_mode=DbChat.JOIN_CAPTCHA)
    session.add(row)
    await session.commit()
    return row


def _press(user_id: int) -> AsyncMock:
    callback = AsyncMock()
    callback.from_user = SimpleNamespace(id=user_id, full_name="Azamat")
    return callback


def _request(user_id: int) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=user_id, is_bot=False, first_name="Applicant"),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


async def test_the_right_tap_is_acknowledged(session: AsyncSession, bot, chat) -> None:
    await service.admit(bot, session, _request(USER_ID), chat)
    row = await session.scalar(select(JoinCaptcha))
    assert row is not None
    callback = _press(USER_ID)

    await captcha_pick(callback, CaptchaPick(challenge_id=row.id, pick=row.options.index(row.answer)), bot, session)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=CHAT_ID, user_id=USER_ID)
    callback.answer.assert_awaited_once()


async def test_a_forwarded_captcha_does_nothing_for_someone_else(session: AsyncSession, bot, chat) -> None:
    await service.admit(bot, session, _request(USER_ID), chat)
    row = await session.scalar(select(JoinCaptcha))
    assert row is not None
    callback = _press(OUTSIDER_ID)

    await captcha_pick(callback, CaptchaPick(challenge_id=row.id, pick=row.options.index(row.answer)), bot, session)

    bot.approve_chat_join_request.assert_not_awaited()
    callback.answer.assert_awaited_once()


async def test_a_wrong_tap_says_what_to_tap_in_a_popup_that_goes_by_itself(session: AsyncSession, bot, chat) -> None:
    await service.admit(bot, session, _request(USER_ID), chat)
    row = await session.scalar(select(JoinCaptcha))
    assert row is not None
    wrong = next(i for i, emoji in enumerate(row.options) if emoji != row.answer)
    callback = _press(USER_ID)

    await captcha_pick(callback, CaptchaPick(challenge_id=row.id, pick=wrong), bot, session)

    name = dict(EMOJI)[row.answer].upper()
    callback.answer.assert_awaited_once_with(f"Не то — нажми на {name}. Осталась 1 попытка")


async def _wave(session: AsyncSession, bot, chat) -> JoinWave:
    now = utc_now()
    for user_id in range(1, waves.PER_MINUTE + 4):
        await service.admit(bot, session, _request(user_id), chat, now=now)
    wave = await session.scalar(select(JoinWave))
    assert wave is not None
    return wave


async def test_only_a_super_admin_decides_a_wave(session: AsyncSession, bot, chat) -> None:
    wave = await _wave(session, bot, chat)
    callback = _press(OUTSIDER_ID)

    await wave_decision(callback, WaveDecision(wave_id=wave.id, action=waves.DECLINE), bot, session)

    callback.answer.assert_awaited_with("Только для супер-админов", show_alert=True)
    bot.decline_chat_join_request.assert_not_awaited()
    await session.refresh(wave)
    assert wave.decision is None


async def test_a_super_admin_declines_the_wave(session: AsyncSession, bot, chat) -> None:
    wave = await _wave(session, bot, chat)
    callback = _press(ADMIN_ID)

    await wave_decision(callback, WaveDecision(wave_id=wave.id, action=waves.DECLINE), bot, session)

    assert bot.decline_chat_join_request.await_count == 3
    await session.refresh(wave)
    assert wave.decision == JoinWave.DECISION_DECLINE
    assert wave.decided_by == ADMIN_ID


async def test_a_wave_decided_otherwise_says_so(session: AsyncSession, bot, chat) -> None:
    wave = await _wave(session, bot, chat)
    await wave_decision(_press(ADMIN_ID), WaveDecision(wave_id=wave.id, action=waves.LEAVE), bot, session)
    callback = _press(ADMIN_ID)

    await wave_decision(callback, WaveDecision(wave_id=wave.id, action=waves.DECLINE), bot, session)

    callback.answer.assert_awaited_once_with("По этой волне уже решили иначе", show_alert=True)
    bot.decline_chat_join_request.assert_not_awaited()


def test_both_handlers_answer_their_presses_themselves() -> None:
    """The dispatcher's automatic answer would be a second answer to the same press."""
    from app.presentation.telegram.handlers.captcha import router

    handlers = router.callback_query.handlers
    assert len(handlers) == 2
    assert all(h.flags.get("callback_answer") == {"disabled": True} for h in handlers)
