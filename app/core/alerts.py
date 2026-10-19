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
import json
import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_LOGGER_NAME = "core.alerts"
logger = logging.getLogger(_LOGGER_NAME)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _event_of(record: logging.LogRecord) -> str:
    """What happened, without the data it happened to."""
    if isinstance(record.msg, dict):
        return str(record.msg.get("event", "?"))
    if record.args:
        # A library's %-template: the arguments are where the data is.
        return str(record.msg)[:120]
    text = str(record.msg)
    if text.startswith("{"):
        try:
            return str(json.loads(text).get("event", "?"))
        except ValueError:
            pass
    return _ANSI.sub("", text).splitlines()[0][:120] if text else "?"


class AlertHandler(logging.Handler):
    """A root-logger handler that queues error records for `run` to send."""

    def __init__(self, *, process: str, throttle_seconds: float = 1800, max_queued: int = 20) -> None:
        super().__init__(level=logging.ERROR)
        self.process = process
        self.throttle_seconds = throttle_seconds
        self._max_queued = max_queued
        self._last_sent: dict[tuple[str, str], float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[str] | None = None

    async def run(self, send: Callable[[str], Awaitable[object]]) -> None:
        """Install the handler and send what it queues, until cancelled."""
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(self._max_queued)
        logging.getLogger().addHandler(self)
        try:
            while True:
                await self._send(send, await self._queue.get())
        except asyncio.CancelledError:
            # The process is stopping, often because of what was just logged:
            # a stalled poller ends it at once. Send what is queued, briefly.
            while not self._queue.empty():
                try:
                    await asyncio.wait_for(self._send(send, self._queue.get_nowait()), timeout=5)
                except TimeoutError:
                    break
            raise
        finally:
            logging.getLogger().removeHandler(self)

    async def _send(self, send: Callable[[str], Awaitable[object]], text: str) -> None:
        try:
            await send(text)
        except Exception as err:
            # A warning, so a failing send cannot alert about itself.
            logger.warning("alert_not_sent: %s", type(err).__name__)

    def emit(self, record: logging.LogRecord) -> None:
        if self._loop is None or record.name == _LOGGER_NAME:
            return
        try:
            event = _event_of(record)
            key = (record.name, event)
            now = time.monotonic()
            if now - self._last_sent.get(key, -self.throttle_seconds) < self.throttle_seconds:
                return
            self._last_sent[key] = now
            text = f"⚠️ {self.process}: {event}\n{record.name}"
            self._loop.call_soon_threadsafe(self._enqueue, text)
        except Exception:
            self.handleError(record)

    def _enqueue(self, text: str) -> None:
        if self._queue is not None and not self._queue.full():
            self._queue.put_nowait(text)
