"""Every line logged while an update is handled says which update, and which handler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from aiogram.dispatcher.event.handler import HandlerObject
from aiogram.types import Chat, Message, MessageEntity, Update
from app.presentation.telegram.middlewares import logging_context
from app.presentation.telegram.middlewares.logging_context import HandlerNameMiddleware, LoggingContextMiddleware

pytestmark = [pytest.mark.asyncio, pytest.mark.middleware]


@pytest.fixture(autouse=True)
def uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """structlog caches a logger on first use, and then `capture_logs` cannot reach it."""
    monkeypatch.setattr(logging_context, "logger", structlog.get_logger("bot.update"))


def _update(update_id: int = 77) -> Update:
    message = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=-1001, type="supergroup"), text="secret words")
    return Update(update_id=update_id, message=message)


def _capture():
    return structlog.testing.capture_logs(processors=[structlog.contextvars.merge_contextvars])


async def test_lines_carry_update_id_type_and_chat() -> None:
    async def handler(event: Any, data: dict[str, Any]) -> None:
        structlog.get_logger("test").info("inside")

    with _capture() as logs:
        await LoggingContextMiddleware()(handler, _update(), {})

    assert logs[0]["update_id"] == 77
    assert logs[0]["update_type"] == "message"
    assert logs[0]["chat_id"] == -1001
    assert "user_id" not in logs[0]  # the audience's ids stay out of the logs
    assert "secret words" not in str(logs)


async def test_the_context_ends_with_the_update() -> None:
    async def handler(event: Any, data: dict[str, Any]) -> None:
        return None

    await LoggingContextMiddleware()(handler, _update(), {})

    with _capture() as logs:
        structlog.get_logger("test").info("after")
    assert "update_id" not in logs[0]


async def test_the_handler_is_named_on_lines_it_writes() -> None:
    async def ban_command() -> None: ...

    async def inner(event: Any, data: dict[str, Any]) -> None:
        structlog.get_logger("test").info("inside")

    async def outer(event: Any, data: dict[str, Any]) -> None:
        await HandlerNameMiddleware()(inner, event, {"handler": HandlerObject(callback=ban_command)})

    with _capture() as logs:
        await LoggingContextMiddleware()(outer, _update(), {})

    assert logs[0]["handler"].endswith("ban_command")


async def test_a_failure_is_logged_once_with_context_and_still_raised() -> None:
    async def ban_command() -> None: ...

    async def failing(event: Any, data: dict[str, Any]) -> None:
        raise ValueError("boom")

    async def outer(event: Any, data: dict[str, Any]) -> None:
        await HandlerNameMiddleware()(failing, event, {"handler": HandlerObject(callback=ban_command)})

    with _capture() as logs, pytest.raises(ValueError, match="boom"):
        await LoggingContextMiddleware()(outer, _update(), {})

    [line] = [log for log in logs if log["event"] == "update_failed"]
    assert line["log_level"] == "error"
    assert line["update_id"] == 77
    assert line["chat_id"] == -1001
    assert line["handler"].endswith("ban_command")
    assert line["error_type"] == "ValueError"
    assert line["exc_info"]


async def test_cancellation_is_not_a_failure() -> None:
    import asyncio

    async def cancelled(event: Any, data: dict[str, Any]) -> None:
        raise asyncio.CancelledError

    with _capture() as logs, pytest.raises(asyncio.CancelledError):
        await LoggingContextMiddleware()(cancelled, _update(), {})

    assert [log for log in logs if log["event"] == "update_failed"] == []


def test_aiograms_own_report_is_dropped_only_for_a_failure_this_middleware_reported() -> None:
    import logging

    exc = ValueError("boom")

    def record(msg: str, error: BaseException | None) -> logging.LogRecord:
        info = (type(error), error, None) if error else None
        return logging.LogRecord("aiogram.event", logging.ERROR, __file__, 1, msg, None, info)

    report = "Cause exception while process update id=1 by bot id=2\nX: y"
    filter_ = logging_context.AlreadyReported()

    # A dispatcher without the middleware (the ads desk, the retired bots): aiogram's is the only report.
    assert filter_.filter(record(report, exc)) is True
    setattr(exc, logging_context.REPORTED, True)
    assert filter_.filter(record(report, exc)) is False
    assert filter_.filter(record("Update id=1 is handled. Duration 5 ms", None)) is True


def test_the_dispatcher_names_handlers_on_every_event_but_updates_and_errors() -> None:
    from aiogram import Bot
    from app.presentation.telegram.bot import build_dispatcher

    dp = build_dispatcher(Bot(token="1:x"), None)  # ty: ignore[invalid-argument-type]

    def has_name(observer) -> bool:
        return any(isinstance(m, logging_context.HandlerNameMiddleware) for m in observer.middleware)

    assert has_name(dp.message)
    assert has_name(dp.callback_query)
    assert has_name(dp.chat_join_request)
    assert not has_name(dp.update)
    assert not has_name(dp.errors)


async def test_a_handler_in_an_included_router_is_named_and_a_failure_is_reported_once() -> None:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.filters import Command

    dp = Dispatcher()
    dp.update.outer_middleware(LoggingContextMiddleware())
    dp.message.middleware(HandlerNameMiddleware())
    child = Router()

    @child.message(Command("ban"))
    async def ban_command(message: Message) -> None:
        structlog.get_logger("test").info("inside")
        raise ValueError("boom")

    dp.include_router(child)
    update = Update(
        update_id=77,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=-1001, type="supergroup"),
            text="/ban",
            entities=[MessageEntity(type="bot_command", offset=0, length=4)],
        ),
    )

    with _capture() as logs, pytest.raises(ValueError, match="boom"):
        await dp.feed_update(Bot(token="1:x"), update)

    assert next(log for log in logs if log["event"] == "inside")["handler"].endswith("ban_command")
    [failed] = [log for log in logs if log["event"] == "update_failed"]
    assert failed["handler"].endswith("ban_command")
    assert failed["chat_id"] == -1001


async def test_a_private_chat_is_not_bound_because_its_id_is_the_persons() -> None:
    private = Update(
        update_id=5,
        message=Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=4242, type="private"), text="hi"),
    )

    async def handler(event: Any, data: dict[str, Any]) -> None:
        structlog.get_logger("test").info("inside")

    with _capture() as logs:
        await LoggingContextMiddleware()(handler, private, {})

    assert logs[0]["update_id"] == 5
    assert "chat_id" not in logs[0]
    assert "4242" not in str(logs)


async def test_a_failure_marks_its_exception_as_reported() -> None:
    async def failing(event: Any, data: dict[str, Any]) -> None:
        raise ValueError("boom")

    with _capture(), pytest.raises(ValueError, match="boom") as raised:
        await LoggingContextMiddleware()(failing, _update(), {})

    assert getattr(raised.value, logging_context.REPORTED) is True
