"""Errors reach the operator's chat, without what they were about."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from app.core import alerts

pytestmark = pytest.mark.asyncio


async def _collect(records: list[tuple[str, str]], *, throttle: float = 1800) -> list[str]:
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    handler = alerts.AlertHandler(process="bot", throttle_seconds=throttle)
    task = asyncio.create_task(handler.run(send))
    await asyncio.sleep(0)  # let it install itself
    for name, message in records:
        logging.getLogger(name).error(message)
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logging.getLogger().removeHandler(handler)
    return sent


async def test_an_error_is_sent_by_its_event_name_only() -> None:
    """The rendered line can carry a DSN or a person's text; the event name cannot."""
    line = json.dumps({"event": "save_message_failed", "error": "password=hunter2", "level": "error"})

    sent = await _collect([("middleware.history", line)])

    assert len(sent) == 1
    assert "save_message_failed" in sent[0]
    assert "middleware.history" in sent[0]
    assert "hunter2" not in sent[0]


async def test_a_library_error_is_sent_by_its_template() -> None:
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    handler = alerts.AlertHandler(process="bot")
    task = asyncio.create_task(handler.run(send))
    await asyncio.sleep(0)  # let it install itself
    logging.getLogger("aiogram.dispatcher").error(
        "Failed to fetch updates - %s: %s", "TelegramNetworkError", "token=abc"
    )
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logging.getLogger().removeHandler(handler)

    assert len(sent) == 1
    assert "Failed to fetch updates" in sent[0]
    assert "token=abc" not in sent[0]


async def test_the_same_error_is_sent_once_per_throttle_window() -> None:
    """A loop failing every second must not become a message every second."""
    line = json.dumps({"event": "snapshot_failed"})

    sent = await _collect([("chats.snapshots", line)] * 5)

    assert len(sent) == 1


async def test_warnings_are_not_sent() -> None:
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    handler = alerts.AlertHandler(process="bot")
    task = asyncio.create_task(handler.run(send))
    await asyncio.sleep(0)  # let it install itself
    logging.getLogger("x").warning("just a warning")
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logging.getLogger().removeHandler(handler)

    assert sent == []


async def test_a_failure_to_send_does_not_alert_about_itself() -> None:
    attempts = 0

    async def send(_text: str) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("telegram is down")

    handler = alerts.AlertHandler(process="bot")
    task = asyncio.create_task(handler.run(send))
    await asyncio.sleep(0)  # let it install itself
    logging.getLogger("x").error(json.dumps({"event": "boom"}))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logging.getLogger().removeHandler(handler)

    assert attempts == 1


async def test_what_was_queued_is_sent_when_the_process_stops() -> None:
    """The watchdog logs a stall and the process ends at once; that alert matters most."""
    sent: list[str] = []
    gate = asyncio.Event()

    async def send(text: str) -> None:
        await gate.wait()
        sent.append(text)

    handler = alerts.AlertHandler(process="bot")
    task = asyncio.create_task(handler.run(send))
    await asyncio.sleep(0)
    logging.getLogger("a").error(json.dumps({"event": "first"}))
    logging.getLogger("b").error(json.dumps({"event": "polling_stalled"}))
    await asyncio.sleep(0.01)
    task.cancel()
    gate.set()
    await asyncio.gather(task, return_exceptions=True)

    assert any("polling_stalled" in text for text in sent)
