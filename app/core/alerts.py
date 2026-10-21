"""Error-level logs, sent to the operator's chat.

Nothing else watches production: the ad detector saved nothing for its whole
life and dropped updates went unseen until someone read logs by hand. An error
is now a message in the report chat, throttled per kind so a loop failing
every second stays one message.

Only the event's name is sent, never the line. A rendered line can carry a
DSN, a token in a URL or a person's text, and the report chat is a chat
history; the name says where to look, the log on the host says the rest.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING

from app.core.metrics import ALERTS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_LOGGER_NAME = "core.alerts"
logger = logging.getLogger(_LOGGER_NAME)

# uvicorn's error logger does not propagate to the root, and it is where an
# unhandled exception in a route is reported.
_ALSO_WATCHED = ("uvicorn.error",)


def _event_of(record: logging.LogRecord) -> str:
    """What happened, without the data it happened to."""
    # Set by app.core.logging on every structlog line, whichever renderer.
    name = getattr(record, "structlog_event", None)
    if name is None:
        if record.args:
            # A library's %-template: the arguments are where the data is.
            name = str(record.msg)
        else:
            text = str(record.msg)
            try:
                name = str(json.loads(text).get("event", "?")) if text.startswith("{") else text.splitlines()[0]
            except (ValueError, IndexError):
                name = "?"
    name = name[:120]
    if record.exc_info and record.exc_info[0] is not None:
        # The class says which bug; the message might say whose data.
        name = f"{name} ({record.exc_info[0].__name__})"
    return name


def _is_noise(record: logging.LogRecord) -> bool:
    """Telegram's transient 5xx and timeouts; a real stall is the watchdog's to report."""
    return record.name == "aiogram.dispatcher" and str(record.msg).startswith("Failed to fetch updates")


class AlertHandler(logging.Handler):
    """Queues error records from this process and sends them to the report chat."""

    def __init__(self, *, process: str, throttle_seconds: float = 1800, max_queued: int = 20) -> None:
        super().__init__(level=logging.ERROR)
        self.process = process
        self.throttle_seconds = throttle_seconds
        self._max_queued = max_queued
        self._last_sent: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[str] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self, send: Callable[[str], Awaitable[object]]) -> None:
        """Begin watching this process's errors; call `stop` to end."""
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(self._max_queued)
        for name in ("", *_ALSO_WATCHED):
            logging.getLogger(name).addHandler(self)
        self._task = asyncio.create_task(self._run(send))

    async def stop(self, timeout: float = 5) -> None:
        """Send what is queued, briefly, then stop.

        The process is usually stopping because of what was just logged: a
        stalled poller ends it at once, and that alert matters most.
        """
        await asyncio.sleep(0)  # let records logged just now reach the queue
        if self._queue is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._queue.join(), timeout)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for name in ("", *_ALSO_WATCHED):
            logging.getLogger(name).removeHandler(self)

    async def _run(self, send: Callable[[str], Awaitable[object]]) -> None:
        assert self._queue is not None
        while True:
            text = await self._queue.get()
            try:
                await send(text)
                ALERTS.labels(outcome="sent").inc()
            except Exception as err:
                ALERTS.labels(outcome="failed").inc()
                # A warning, so a failing send cannot alert about itself.
                logger.warning("alert_not_sent: %s", type(err).__name__)
            finally:
                self._queue.task_done()

    def emit(self, record: logging.LogRecord) -> None:
        if self._loop is None or record.name == _LOGGER_NAME or _is_noise(record):
            return
        try:
            event = _event_of(record)
            self._loop.call_soon_threadsafe(self._enqueue, f"{record.name}: {event}")
        except Exception:
            self.handleError(record)

    def _enqueue(self, key: str) -> None:
        """On the loop's thread, so the throttle needs no lock."""
        now = time.monotonic()
        if self._queue is None or self._queue.full():
            return
        if now - self._last_sent.get(key, -self.throttle_seconds) < self.throttle_seconds:
            return
        # Stamped only once queued, so a full queue cannot mute a kind for the window.
        self._last_sent[key] = now
        self._queue.put_nowait(f"⚠️ {self.process}: {key}")
