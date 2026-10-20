"""A wave of join requests pauses the captcha instead of feeding it.

Thousands of farmed accounts asking to join at once would have the bot write
thousands of private messages and burn its rate limit on them. Past a
threshold the bot stops writing: requests wait in Telegram, nobody gets in,
and the report chat gets one message whose buttons decide the wave.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import service, waves
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha, JoinWave
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit

CHAT_ID = -1001370017010
ADMIN_ID = settings.admin.super_admins[0]
T0 = utc_now()


def _request(user_id: int) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=user_id, is_bot=False, first_name=f"bot{user_id}"),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


@pytest.fixture
async def chat(session: AsyncSession) -> DbChat:
    row = DbChat(id=CHAT_ID, title="ČVUT FIT", resource_status=DbChat.STATUS_APPROVED, is_captcha_enabled=True)
    session.add(row)
    await session.commit()
    return row


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    sent = MagicMock()
    sent.message_id = 500
    tg_bot.send_message = AsyncMock(return_value=sent)
    tg_bot.edit_message_text = AsyncMock()
    tg_bot.decline_chat_join_request = AsyncMock()
    tg_bot.approve_chat_join_request = AsyncMock()
    return tg_bot


async def _flood(bot, session, chat, count: int, *, start: int = 1, at: datetime.datetime = T0) -> None:
    for user_id in range(start, start + count):
        await service.admit(bot, session, _request(user_id), chat, now=at)


def _captchas_sent(bot) -> int:
    report_chat = settings.admin.default_report_chat_id
    return sum(1 for call in bot.send_message.await_args_list if call.kwargs["chat_id"] != report_chat)


def _alerts(bot) -> list:
    return [
        call
        for call in bot.send_message.await_args_list
        if call.kwargs["chat_id"] == settings.admin.default_report_chat_id
    ]


async def _count(session: AsyncSession, status: str) -> int:
    return await session.scalar(select(func.count()).select_from(JoinCaptcha).where(JoinCaptcha.status == status)) or 0


async def test_an_ordinary_trickle_is_not_a_wave(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE)

    assert _captchas_sent(bot) == waves.PER_MINUTE
    assert _alerts(bot) == []


async def test_past_the_threshold_nobody_else_is_written_to(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 30)

    assert _captchas_sent(bot) == waves.PER_MINUTE
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 30
    bot.approve_chat_join_request.assert_not_awaited()
    bot.decline_chat_join_request.assert_not_awaited()


async def test_one_alert_per_wave_with_its_buttons(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 30)

    alerts = _alerts(bot)
    assert len(alerts) == 1
    assert "ČVUT FIT" in alerts[0].kwargs["text"]
    labels = [b.text for row in alerts[0].kwargs["reply_markup"].inline_keyboard for b in row]
    assert labels == ["Отклонить все", "Снять паузу", "Пусть висят"]
    assert await session.scalar(select(func.count()).select_from(JoinWave)) == 1


async def test_the_pause_outlasts_the_burst_and_then_lifts(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 1)

    # A real person turning up five minutes later still waits: the wave may resume.
    await service.admit(bot, session, _request(9001), chat, now=T0 + datetime.timedelta(minutes=5))
    assert _captchas_sent(bot) == waves.PER_MINUTE

    # A quarter of an hour of quiet ends it.
    later = T0 + datetime.timedelta(minutes=waves.QUIET_MINUTES + 1)
    await service.admit(bot, session, _request(9002), chat, now=later)
    assert _captchas_sent(bot) == waves.PER_MINUTE + 1


async def test_declining_the_wave_turns_away_everyone_held_and_who_comes_next(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 5)
    wave = await session.scalar(select(JoinWave))
    assert wave is not None

    note = await waves.decide(
        bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="Azamat"
    )

    assert note is not None
    assert bot.decline_chat_join_request.await_count == 5
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 0
    assert "Отклонено 5" in bot.edit_message_text.await_args.kwargs["text"]

    # Still the same wave: the next one through the door is declined on sight.
    await service.admit(bot, session, _request(7000), chat, now=T0 + datetime.timedelta(minutes=1))
    assert bot.decline_chat_join_request.await_count == 6
    assert _captchas_sent(bot) == waves.PER_MINUTE


async def test_resuming_sends_the_captcha_to_new_requests(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 5)
    wave = await session.scalar(select(JoinWave))
    assert wave is not None

    await waves.decide(bot, session, wave_id=wave.id, action=waves.RESUME, admin_id=ADMIN_ID, admin_name="Azamat")
    await service.admit(bot, session, _request(7000), chat, now=T0 + datetime.timedelta(minutes=2))

    assert _captchas_sent(bot) == waves.PER_MINUTE + 1
    # The ones already held are past the window Telegram gives for writing to them.
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 5
    bot.decline_chat_join_request.assert_not_awaited()


async def test_leaving_them_keeps_the_pause_and_the_requests(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 5)
    wave = await session.scalar(select(JoinWave))
    assert wave is not None

    await waves.decide(bot, session, wave_id=wave.id, action=waves.LEAVE, admin_id=ADMIN_ID, admin_name="Azamat")
    await service.admit(bot, session, _request(7000), chat, now=T0 + datetime.timedelta(minutes=2))

    assert _captchas_sent(bot) == waves.PER_MINUTE
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 6
    bot.decline_chat_join_request.assert_not_awaited()


async def test_a_wave_is_decided_once(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 5)
    wave = await session.scalar(select(JoinWave))
    assert wave is not None

    await waves.decide(bot, session, wave_id=wave.id, action=waves.LEAVE, admin_id=ADMIN_ID, admin_name="Azamat")
    again = await waves.decide(
        bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="Azamat"
    )

    assert again is None
    bot.decline_chat_join_request.assert_not_awaited()


# --- review ------------------------------------------------------------------


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=MagicMock(), message=f"Bad Request: {message}")


async def _the_wave(session: AsyncSession) -> JoinWave:
    wave = await session.scalar(select(JoinWave).order_by(JoinWave.id.desc()))
    assert wave is not None
    return wave


async def test_one_person_asking_many_times_is_not_a_wave(session: AsyncSession, bot, chat) -> None:
    for _ in range(waves.PER_MINUTE + 5):
        await service.admit(bot, session, _request(42), chat, now=T0)

    assert _alerts(bot) == []


async def test_a_burst_that_goes_on_after_a_resume_is_a_new_wave(session: AsyncSession, bot, chat) -> None:
    """Resuming must not switch the safeguard off for the rest of the raid."""
    await _flood(bot, session, chat, waves.PER_MINUTE + 5)
    first = await _the_wave(session)
    await waves.decide(bot, session, wave_id=first.id, action=waves.RESUME, admin_id=ADMIN_ID, admin_name="A", now=T0)

    later = T0 + datetime.timedelta(seconds=10)
    await _flood(bot, session, chat, waves.PER_MINUTE + 50, start=1000, at=later)

    second = await _the_wave(session)
    assert second.id != first.id
    assert len(_alerts(bot)) == 2
    assert _captchas_sent(bot) == 2 * waves.PER_MINUTE
    held = (await session.scalars(select(JoinCaptcha).where(JoinCaptcha.status == JoinCaptcha.STATUS_HELD))).all()
    assert {r.wave_id for r in held if r.user_id >= 1000} == {second.id}


async def test_a_burst_that_returns_keeps_the_pause(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 1)
    await _flood(bot, session, chat, waves.PER_MINUTE + 1, start=500, at=T0 + datetime.timedelta(minutes=10))

    await service.admit(bot, session, _request(9000), chat, now=T0 + datetime.timedelta(minutes=20))

    assert len(_alerts(bot)) == 1
    assert _captchas_sent(bot) == waves.PER_MINUTE
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 1 + waves.PER_MINUTE + 1 + 1


async def test_the_alert_count_keeps_up(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 7)

    await waves.refresh_alerts(bot, session, T0)

    edit = bot.edit_message_text.await_args.kwargs
    assert edit["message_id"] == 500
    assert "Ждут решения: 7" in edit["text"]


async def test_declines_that_fail_are_left_for_another_press(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 3)
    wave = await _the_wave(session)
    bot.decline_chat_join_request.side_effect = [None, _bad_request("CHAT_ADMIN_REQUIRED"), None]

    note = await waves.decide(bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="A")

    assert note is not None
    assert "Отклонено 2" in note
    assert "Не удалось отклонить 1" in note
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 1

    bot.decline_chat_join_request.side_effect = None
    again = await waves.decide(bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="A")

    assert again is not None
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 0


async def test_requests_settled_meanwhile_are_not_counted_as_declined(session: AsyncSession, bot, chat) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 2)
    wave = await _the_wave(session)
    bot.decline_chat_join_request.side_effect = [None, _bad_request("HIDE_REQUESTER_MISSING")]

    note = await waves.decide(bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="A")

    assert note is not None
    assert "Отклонено 1 " in note
    assert await _count(session, JoinCaptcha.STATUS_GONE) == 1


async def test_declining_a_wave_in_a_chat_that_dropped_captcha_declines_nobody(
    session: AsyncSession, bot, chat
) -> None:
    await _flood(bot, session, chat, waves.PER_MINUTE + 3)
    wave = await _the_wave(session)
    chat.is_captcha_enabled = False
    await session.commit()

    await waves.decide(bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=ADMIN_ID, admin_name="A")

    bot.decline_chat_join_request.assert_not_awaited()
    assert await _count(session, JoinCaptcha.STATUS_HELD) == 3
