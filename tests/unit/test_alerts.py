"""Errors reach the operator's chat, without what they were about."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
import structlog
from app.core import alerts
from app.core.logging import setup_logging

pytestmark = pytest.mark.asyncio


class Outbox:
    def __init__(self, delay: float = 0) -> None:
        self.sent: list[str] = []
        self.delay = delay

    async def __call__(self, text: str) -> None:
        await asyncio.sleep(self.delay)
        self.sent.append(text)


async def _run(log, *, outbox: Outbox | None = None, **handler_kwargs) -> list[str]:
    outbox = outbox or Outbox()
    handler = alerts.AlertHandler(process="bot", **handler_kwargs)
    handler.start(outbox)
    log()
    await handler.stop()
    return outbox.sent


async def test_a_structlog_error_is_sent_by_its_event_name_only() -> None:
    """Whatever the renderer, the line can carry a DSN or a person's text; the name cannot."""
    setup_logging()

    sent = await _run(lambda: structlog.get_logger("middleware.history").error("save_failed", error="password=hunter2"))

    assert sent == ["⚠️ bot: middleware.history: save_failed"]


async def test_a_json_line_from_elsewhere_is_sent_by_its_event() -> None:
    line = json.dumps({"event": "save_message_failed", "error": "password=hunter2"})

    sent = await _run(lambda: logging.getLogger("x").error(line))

    assert sent == ["⚠️ bot: x: save_message_failed"]


async def test_a_library_error_is_sent_by_its_template() -> None:
    sent = await _run(lambda: logging.getLogger("lib").error("Could not reach %s with %s", "host", "token=abc"))

    assert len(sent) == 1
    assert "Could not reach" in sent[0]
    assert "token=abc" not in sent[0]


async def test_the_exception_class_is_part_of_what_is_sent() -> None:
    """aiogram reports every handler failure with one template; the class tells them apart."""

    def log() -> None:
        try:
            raise KeyError("person 42")
        except KeyError:
            logging.getLogger("aiogram.event").exception("Cause exception while process update %s", 1)

    sent = await _run(log)

    assert sent == ["⚠️ bot: aiogram.event: Cause exception while process update %s (KeyError)"]


async def test_the_same_error_is_sent_once_per_throttle_window() -> None:
    sent = await _run(lambda: [logging.getLogger("loop").error(json.dumps({"event": "tick_failed"})) for _ in range(5)])

    assert len(sent) == 1


async def test_transient_fetch_failures_are_not_sent() -> None:
    """Telegram's 5xx comes and goes; a poller that stays down is the watchdog's to report."""
    sent = await _run(lambda: logging.getLogger("aiogram.dispatcher").error("Failed to fetch updates - %s", "5xx"))

    assert sent == []


async def test_warnings_are_not_sent() -> None:
    sent = await _run(lambda: logging.getLogger("x").warning("just a warning"))

    assert sent == []


async def test_a_failure_to_send_does_not_alert_about_itself() -> None:
    attempts = 0

    async def failing(_text: str) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("telegram is down")

    handler = alerts.AlertHandler(process="bot")
    handler.start(failing)
    logging.getLogger("x").error(json.dumps({"event": "boom"}))
    await handler.stop()

    assert attempts == 1


async def test_the_last_error_before_stopping_is_still_sent() -> None:
    """The watchdog logs a stall and the process ends at once; that alert matters most."""
    outbox = Outbox(delay=0.05)

    sent = await _run(
        lambda: logging.getLogger("bot.heartbeat").error(json.dumps({"event": "polling_stalled"})), outbox=outbox
    )

    assert sent == ["⚠️ bot: bot.heartbeat: polling_stalled"]


async def test_a_full_queue_does_not_mute_a_kind_of_error() -> None:
    outbox = Outbox(delay=0.01)
    handler = alerts.AlertHandler(process="bot", max_queued=1)
    handler.start(outbox)
    for i in range(3):
        logging.getLogger("x").error(json.dumps({"event": f"first-{i}"}))
    await asyncio.sleep(0.05)
    logging.getLogger("x").error(json.dumps({"event": "first-2"}))
    await handler.stop()

    assert "⚠️ bot: x: first-2" in outbox.sent


async def test_uvicorn_route_crashes_are_seen_although_they_do_not_propagate() -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.propagate = False
    try:
        sent = await _run(lambda: uvicorn_error.error("Exception in ASGI application\n"))
    finally:
        uvicorn_error.propagate = True

    assert sent == ["⚠️ bot: uvicorn.error: Exception in ASGI application"]
