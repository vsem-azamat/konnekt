"""The join captcha under concurrency, on PostgreSQL.

The bot handles updates as concurrent tasks, so a wave arrives as a hundred
requests at once, a nervous applicant taps twice, and the expiry sweep runs
while somebody is answering. SQLite runs one of each at a time and cannot show
any of this; these tests need the locks PostgreSQL actually takes.
"""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, ChatJoinRequest, User
from app.captcha import service, waves
from app.core.config import settings
from app.core.time import utc_now
from app.db.models import Chat as DbChat
from app.db.models import JoinCaptcha, JoinWave
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

CHAT_ID = -1001370017010
T0 = utc_now()


def _request(user_id: int) -> ChatJoinRequest:
    return ChatJoinRequest(
        chat=Chat(id=CHAT_ID, type="supergroup", title="ČVUT FIT"),
        from_user=User(id=user_id, is_bot=False, first_name="Applicant"),
        user_chat_id=user_id,
        date=datetime.datetime.now(datetime.UTC),
    )


def _slow(delay: float) -> AsyncMock:
    async def call(**_: object) -> MagicMock:
        await asyncio.sleep(delay)
        return MagicMock(message_id=1)

    return AsyncMock(side_effect=call)


@pytest.fixture
def bot() -> MagicMock:
    tg_bot = MagicMock()
    tg_bot.send_message = _slow(0.01)
    tg_bot.edit_message_text = _slow(0)
    tg_bot.approve_chat_join_request = _slow(0.2)
    tg_bot.decline_chat_join_request = _slow(0.01)
    return tg_bot


@pytest.fixture
async def chat(pg_session_maker: async_sessionmaker[AsyncSession]) -> DbChat:
    async with pg_session_maker() as session:
        row = DbChat(id=CHAT_ID, title="ČVUT FIT", resource_status=DbChat.STATUS_APPROVED, is_captcha_enabled=True)
        session.add(row)
        await session.commit()
        return row


async def _admit(maker: async_sessionmaker[AsyncSession], bot, user_id: int) -> None:
    async with maker() as session:
        chat = await session.get(DbChat, CHAT_ID)
        assert chat is not None
        await service.admit(bot, session, _request(user_id), chat, now=T0)


async def test_a_burst_opens_one_wave_and_writes_to_no_more_than_the_threshold(pg_session_maker, bot, chat) -> None:
    await asyncio.gather(*(_admit(pg_session_maker, bot, user_id) for user_id in range(1, 101)))

    async with pg_session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(JoinWave)) == 1
        held = await session.scalar(
            select(func.count()).select_from(JoinCaptcha).where(JoinCaptcha.status == JoinCaptcha.STATUS_HELD)
        )
    report_chat = settings.admin.default_report_chat_id
    captchas = [c for c in bot.send_message.await_args_list if c.kwargs["chat_id"] != report_chat]
    assert len(captchas) == waves.PER_MINUTE
    assert held == 100 - waves.PER_MINUTE


async def _pending(maker: async_sessionmaker[AsyncSession], bot) -> JoinCaptcha:
    await _admit(maker, bot, 4242)
    async with maker() as session:
        row = await session.scalar(select(JoinCaptcha))
        assert row is not None
        return row


async def _tap(maker, bot, row: JoinCaptcha, *, now: datetime.datetime | None = None) -> service.Outcome:
    async with maker() as session:
        return await service.answer(
            bot, session, challenge_id=row.id, user_id=row.user_id, pick=row.options.index(row.answer), now=now
        )


async def test_a_double_tap_approves_once(pg_session_maker, bot, chat) -> None:
    row = await _pending(pg_session_maker, bot)

    outcomes = await asyncio.gather(_tap(pg_session_maker, bot, row), _tap(pg_session_maker, bot, row))

    assert sorted(o.value for o in outcomes) == ["closed", "passed"]
    bot.approve_chat_join_request.assert_awaited_once()


async def test_the_sweep_leaves_alone_a_request_being_answered(pg_session_maker, bot, chat) -> None:
    row = await _pending(pg_session_maker, bot)
    just_in_time = row.expires_at - datetime.timedelta(seconds=1)

    async def sweep() -> None:
        await asyncio.sleep(0.05)  # the tap holds the row by now, mid-approve
        async with pg_session_maker() as session:
            await service.expire_stale(bot, session, now=row.expires_at + datetime.timedelta(seconds=1))

    outcome, _ = await asyncio.gather(_tap(pg_session_maker, bot, row, now=just_in_time), sweep())

    assert outcome is service.Outcome.PASSED
    bot.decline_chat_join_request.assert_not_awaited()
    async with pg_session_maker() as session:
        settled = await session.get(JoinCaptcha, row.id)
        assert settled is not None
        assert settled.status == JoinCaptcha.STATUS_PASSED


async def test_two_presses_of_decline_share_the_work(pg_session_maker, bot, chat) -> None:
    await asyncio.gather(*(_admit(pg_session_maker, bot, user_id) for user_id in range(1, 61)))
    async with pg_session_maker() as session:
        wave = await session.scalar(select(JoinWave))
        assert wave is not None

    async def press() -> None:
        async with pg_session_maker() as session:
            await waves.decide(bot, session, wave_id=wave.id, action=waves.DECLINE, admin_id=1, admin_name="A", now=T0)

    await asyncio.gather(press(), press())

    assert bot.decline_chat_join_request.await_count == 60 - waves.PER_MINUTE
    async with pg_session_maker() as session:
        declined = await session.scalar(
            select(func.count()).select_from(JoinCaptcha).where(JoinCaptcha.status == JoinCaptcha.STATUS_DECLINED)
        )
    assert declined == 60 - waves.PER_MINUTE


async def test_two_sweeps_at_once_remind_once(pg_session_maker, bot, chat) -> None:
    """Two bot processes overlap during a deploy, and both run the sweep.

    The first holds its send until the second has looked at the row, so the
    second meets it locked, mid-send, every time rather than by timing luck.
    """
    row = await _pending(pg_session_maker, bot)
    due = row.created_at + datetime.timedelta(minutes=settings.captcha.remind_after_minutes, seconds=10)
    second_done = asyncio.Event()
    sends = 0

    async def send(**_: object) -> MagicMock:
        nonlocal sends
        sends += 1
        await asyncio.wait_for(second_done.wait(), timeout=5)
        return MagicMock(message_id=2)

    bot.send_message = AsyncMock(side_effect=send)

    async def sweep() -> None:
        async with pg_session_maker() as session:
            await service.remind(bot, session, now=due)

    async def second() -> None:
        while sends == 0:
            await asyncio.sleep(0.01)
        await sweep()
        second_done.set()

    await asyncio.gather(sweep(), second())

    assert sends == 1
    async with pg_session_maker() as session:
        settled = await session.get(JoinCaptcha, row.id)
        assert settled is not None
        assert settled.reminded_at == due
