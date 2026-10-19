"""The bot's liveness is its poller answering, not its process existing."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import GetMe, GetUpdates
from app.presentation.telegram import heartbeat

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.asyncio


async def test_every_answered_get_updates_touches_the_heartbeat(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    middleware = heartbeat.PollingHeartbeat(beat)
    make_request = AsyncMock(return_value=[])

    await middleware(make_request, AsyncMock(), GetUpdates())

    assert beat.exists()


async def test_other_calls_do_not_count_as_polling(tmp_path: Path) -> None:
    """A bot that sends but no longer polls is exactly the deaf bot to catch."""
    beat = tmp_path / "beat"
    middleware = heartbeat.PollingHeartbeat(beat)

    await middleware(AsyncMock(), AsyncMock(), GetMe())

    assert not beat.exists()


async def test_a_failed_get_updates_does_not_count(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    middleware = heartbeat.PollingHeartbeat(beat)

    with pytest.raises(ConnectionError):
        await middleware(AsyncMock(side_effect=ConnectionError()), AsyncMock(), GetUpdates())

    assert not beat.exists()


async def test_the_watchdog_ends_the_process_when_polling_stalls(tmp_path: Path) -> None:
    """Stalled for minutes means deaf: exiting lets the container restart."""
    import asyncio

    beat = tmp_path / "beat"
    watching = asyncio.create_task(heartbeat.watch(beat, max_age_seconds=300, interval_seconds=0.01, grace_seconds=60))
    await asyncio.sleep(0.02)
    beat.write_text("")  # polled once, long ago
    stale = time.time() - 600
    os.utime(beat, (stale, stale))

    with pytest.raises(heartbeat.PollingStalledError):
        await asyncio.wait_for(watching, timeout=1)


async def test_a_bot_that_never_polls_is_ended_after_the_grace(tmp_path: Path) -> None:
    import asyncio

    with pytest.raises(heartbeat.PollingStalledError):
        await asyncio.wait_for(
            heartbeat.watch(tmp_path / "beat", max_age_seconds=0.05, interval_seconds=0.01, grace_seconds=0),
            timeout=1,
        )


async def test_the_watchdog_waits_for_the_first_poll(tmp_path: Path) -> None:
    """Before the first getUpdates there is no file; startup gets a grace period."""
    import asyncio

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            heartbeat.watch(tmp_path / "beat", max_age_seconds=300, interval_seconds=0.01, grace_seconds=60),
            timeout=0.1,
        )


async def test_a_heartbeat_left_by_the_previous_process_does_not_count(tmp_path: Path) -> None:
    """After an in-place restart its age would end the new process before it polled."""
    import asyncio

    beat = tmp_path / "beat"
    beat.write_text("")
    stale = time.time() - 600
    os.utime(beat, (stale, stale))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            heartbeat.watch(beat, max_age_seconds=300, interval_seconds=0.01, grace_seconds=60),
            timeout=0.1,
        )
