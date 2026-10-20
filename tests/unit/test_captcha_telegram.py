"""Flood control: short waits are waited out, long ones are not."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from app.captcha import telegram

pytestmark = pytest.mark.unit


def _flood(seconds: int) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=seconds)


async def test_a_short_flood_is_waited_out(monkeypatch) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(telegram.asyncio, "sleep", sleep)
    call = AsyncMock(side_effect=[_flood(3), "done"])

    assert await telegram.with_retry(call) == "done"
    assert slept == [3]


async def test_a_long_flood_is_not_waited_on(monkeypatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr(telegram.asyncio, "sleep", sleep)

    with pytest.raises(TelegramRetryAfter):
        await telegram.with_retry(AsyncMock(side_effect=_flood(61)))
    sleep.assert_not_awaited()


async def test_flood_after_every_attempt_gives_up(monkeypatch) -> None:
    monkeypatch.setattr(telegram.asyncio, "sleep", AsyncMock())
    call = AsyncMock(side_effect=_flood(1))

    with pytest.raises(TelegramRetryAfter):
        await telegram.with_retry(call)
    assert call.await_count == 3
