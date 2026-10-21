"""Say which update, which chat and which handler a log line belongs to.

Without this a line from deep inside a handler is "kick_failed" and nothing
else: to find the update that caused it you grep for the chat and the minute.
The user is left out on purpose: the audience's ids do not go into the logs
(docs/invariants.md), and the moderation calls that do name a person say so in
their own line.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Update

from app.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiogram.types import TelegramObject

logger = get_logger("bot.update")

# The handler is only known once a filter has matched, which is inside the
# outer middleware that has to report the failure: they share a cell.
_handler: ContextVar[list[str] | None] = ContextVar("update_handler", default=None)


def _chat_id(update: Update) -> int | None:
    inner: Any = update.event
    chat = getattr(inner, "chat", None) or getattr(getattr(inner, "message", None), "chat", None)
    return getattr(chat, "id", None)


def handler_name(handler: Any) -> str:
    callback = getattr(handler, "callback", handler)
    module = str(getattr(callback, "__module__", "")).rsplit(".", 1)[-1]
    return f"{module}.{getattr(callback, '__qualname__', repr(callback))}"


class LoggingContextMiddleware(BaseMiddleware):
    """Outermost on updates: binds the context and reports what escapes."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        context: dict[str, Any] = {"update_id": event.update_id, "update_type": event.event_type}
        chat_id = _chat_id(event)
        if chat_id is not None:
            context["chat_id"] = chat_id
        named: list[str] = []
        token = _handler.set(named)
        try:
            with structlog.contextvars.bound_contextvars(**context):
                try:
                    return await handler(event, data)
                except Exception as err:
                    # Here, where the context still holds: by the time aiogram's
                    # own error path logs it, the update is already forgotten.
                    logger.error(
                        "update_failed",
                        handler=named[0] if named else None,
                        error_type=type(err).__name__,
                        exc_info=True,
                    )
                    raise
        finally:
            _handler.reset(token)


class HandlerNameMiddleware(BaseMiddleware):
    """Inner, on each event type: the handler whose filters matched."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        name = handler_name(data["handler"]) if "handler" in data else None
        if name is None:
            return await handler(event, data)
        cell = _handler.get()
        if cell is not None:
            cell[:] = [name]
        with structlog.contextvars.bound_contextvars(handler=name):
            return await handler(event, data)
