"""What the bot tells Prometheus: updates, Bot API calls, the poller's pulse, the queues."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import GetMe, SendMessage
from aiogram.types import Chat, Message, Update
from app.core.config import settings
from app.presentation.telegram import metrics as bot_metrics
from app.presentation.telegram.middlewares.logging_context import LoggingContextMiddleware
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from pydantic import SecretStr

pytestmark = [pytest.mark.asyncio, pytest.mark.middleware]


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _update() -> Update:
    message = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=-1001, type="supergroup"), text="hi")
    return Update(update_id=1, message=message)


async def test_updates_are_counted_by_type_and_outcome_and_timed() -> None:
    ok = sample("bot_updates_total", update_type="message", outcome="ok")
    failed = sample("bot_updates_total", update_type="message", outcome="failed")

    async def fine(event: Any, data: dict[str, Any]) -> None: ...

    async def broken(event: Any, data: dict[str, Any]) -> None:
        raise ValueError("boom")

    await LoggingContextMiddleware()(fine, _update(), {})
    with pytest.raises(ValueError, match="boom"):
        await LoggingContextMiddleware()(broken, _update(), {})

    assert sample("bot_updates_total", update_type="message", outcome="ok") == ok + 1
    assert sample("bot_updates_total", update_type="message", outcome="failed") == failed + 1
    assert sample("bot_update_duration_seconds_count", update_type="message") >= 2


async def test_bot_api_calls_are_counted_by_method_and_outcome() -> None:
    middleware = bot_metrics.ApiCallMetrics()
    ok = sample("bot_telegram_api_calls_total", method="getMe", outcome="ok")
    refused = sample("bot_telegram_api_calls_total", method="sendMessage", outcome="TelegramForbiddenError")

    async def answers(bot: Any, method: Any) -> str:
        return "ok"

    async def refuses(bot: Any, method: Any) -> None:
        raise TelegramForbiddenError(method=SendMessage(chat_id=1, text="x"), message="Forbidden")

    await middleware(answers, None, GetMe())  # ty: ignore[invalid-argument-type]
    with pytest.raises(TelegramForbiddenError):
        await middleware(refuses, None, SendMessage(chat_id=1, text="x"))  # ty: ignore[invalid-argument-type]

    assert sample("bot_telegram_api_calls_total", method="getMe", outcome="ok") == ok + 1
    assert sample("bot_telegram_api_calls_total", method="sendMessage", outcome="TelegramForbiddenError") == refused + 1


async def test_the_pollers_pulse_is_its_age(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    pulse = tmp_path / "bot-heartbeat"
    monkeypatch.setattr(bot_metrics, "HEARTBEAT", pulse)
    assert bot_metrics.heartbeat_age() != bot_metrics.heartbeat_age()  # NaN: no poll answered yet

    pulse.touch()
    os.utime(pulse, (time.time() - 42, time.time() - 42))
    assert 41 < bot_metrics.heartbeat_age() < 50


async def test_the_queues_are_counted_from_the_database(session) -> None:
    from app.core.time import utc_now
    from app.db.models import Chat as DbChat
    from app.db.models import JoinCaptcha, PendingAction

    session.add(DbChat(id=-1001, title="t"))
    now = utc_now()
    for status in (
        JoinCaptcha.STATUS_PENDING,
        JoinCaptcha.STATUS_PENDING,
        JoinCaptcha.STATUS_HELD,
        JoinCaptcha.STATUS_PASSED,
    ):
        session.add(
            JoinCaptcha(
                chat_id=-1001,
                user_id=1,
                user_chat_id=1,
                status=status,
                answer="a",
                options=["a"],
                attempts_left=2,
                created_at=now,
                expires_at=now,
            )  # fmt: skip
        )
    await session.commit()

    await bot_metrics.refresh_queue_depths(session)

    assert sample("bot_queue_depth", queue="captcha_pending") == 2
    assert sample("bot_queue_depth", queue="captcha_held") == 1
    assert sample("bot_queue_depth", queue="pending_actions") == 0
    assert PendingAction  # the third queue is read from the same place


async def test_greetings_past_their_time_are_counted_once_each(session) -> None:
    """A greeting is one message however many joiners extended it; the last join decides."""
    import datetime

    from app.core.time import utc_now
    from app.db.models import WelcomeGreeting

    now = utc_now()
    ago, ahead = now - datetime.timedelta(minutes=5), now + datetime.timedelta(minutes=5)
    session.add_all(
        [
            WelcomeGreeting(-1001, 10, ago),
            WelcomeGreeting(-1001, 10, ago),  # a second joiner, the same message
            WelcomeGreeting(-1002, 20, ago),
            WelcomeGreeting(-1002, 21, ago),
            WelcomeGreeting(-1002, 21, ahead),  # a later joiner keeps it up
            WelcomeGreeting(-1003, 30, ahead),
        ]
    )
    await session.commit()

    await bot_metrics.refresh_queue_depths(session)

    assert sample("bot_queue_depth", queue="welcome_overdue") == 2


async def test_the_scrape_app_is_closed_by_the_token_and_serves_one_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr("s3cret-value"))
    app = bot_metrics.build_metrics_app()
    auth = {"Authorization": "Bearer s3cret-value"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bot") as client:
        assert (await client.get("/metrics")).status_code == 401
        assert (await client.get("/metrics", headers={"Authorization": "Bearer nope"})).status_code == 401
        ok = await client.get("/metrics", headers=auth)
        assert ok.status_code == 200
        assert "bot_updates_total" in ok.text
        # Nothing else is served from here, the control plane's path included.
        assert (await client.get("/api/mcp", headers=auth)).status_code == 404
        assert (await client.post("/metrics", headers=auth)).status_code == 405


async def test_a_scrape_port_that_is_taken_does_not_take_moderation_down(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    taken = socket.socket()
    taken.bind(("0.0.0.0", 0))  # noqa: S104
    taken.listen()
    monkeypatch.setattr(type(settings.observability), "metrics_port", taken.getsockname()[1])
    monkeypatch.setattr(settings.observability, "metrics_secret", SecretStr("s" * 32))
    try:
        # uvicorn answers a port it cannot bind with SystemExit; this must come back.
        await bot_metrics.run_metrics_server()
    finally:
        taken.close()
