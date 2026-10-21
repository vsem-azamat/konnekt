"""The scrape endpoint is closed by a token and absent without one; the counters count."""

import logging

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from httpx import AsyncClient
from prometheus_client import REGISTRY
from pydantic import SecretStr

from students_cz.core.config import get_settings
from students_cz.db.models.enums import UiLang
from students_cz.services.notify import tell

from .conftest import auth_header

ENDPOINT = "/api/v1/internal/metrics"


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def secret(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        get_settings(), "observability_metrics_secret", SecretStr("s3cret-value")
    )
    return "s3cret-value"


async def test_without_a_secret_the_endpoint_does_not_exist(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "observability_metrics_secret", SecretStr(""))

    assert (await client.get(ENDPOINT)).status_code == 404
    assert (
        await client.get(ENDPOINT, headers={"Authorization": "Bearer "})
    ).status_code == 404


async def test_a_wrong_or_missing_token_is_refused(
    client: AsyncClient, secret: str
) -> None:
    assert (await client.get(ENDPOINT)).status_code == 401
    assert (
        await client.get(ENDPOINT, headers={"Authorization": "Bearer nope"})
    ).status_code == 401
    # An initData header is not a metrics token.
    assert (await client.get(ENDPOINT, headers=auth_header())).status_code == 401


async def test_the_right_token_gets_prometheus_text(
    client: AsyncClient, secret: str
) -> None:
    response = await client.get(ENDPOINT, headers={"Authorization": f"Bearer {secret}"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in response.text
    assert "process_resident_memory_bytes" in response.text


async def test_the_endpoint_is_not_in_the_published_contract(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert not [path for path in schema["paths"] if "internal" in path]


async def test_requests_are_counted_by_route_template(client: AsyncClient) -> None:
    labels = {
        "method": "GET",
        "route": "/api/v1/requests/{request_id}/responses",
        "status": "404",
    }
    before = sample("http_requests_total", **labels)

    await client.get("/api/v1/requests/999999/responses", headers=auth_header())
    await client.get("/api/v1/requests/888888/responses", headers=auth_header())

    assert sample("http_requests_total", **labels) == before + 2


async def test_a_scrape_is_not_counted(client: AsyncClient, secret: str) -> None:
    labels = {"method": "GET", "route": ENDPOINT, "status": "200"}
    before = sample("http_requests_total", **labels)

    await client.get(ENDPOINT, headers={"Authorization": f"Bearer {secret}"})

    assert sample("http_requests_total", **labels) == before


class _Bot:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def send_message(self, **_: object) -> None:
        if self.error:
            raise self.error


def _sent(outcome: str) -> float:
    return sample("catalog_notifications_total", outcome=outcome)


async def test_notifications_are_counted_by_what_became_of_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop(*_: object, **__: object) -> None: ...

    monkeypatch.setattr("students_cz.services.notify.mark_unreachable", noop)
    monkeypatch.setattr("students_cz.services.notify.get_sessionmaker", lambda: _Session)
    method = SendMessage(chat_id=1, text="x")
    cases = {
        "sent": None,
        "blocked": TelegramForbiddenError(method=method, message="Forbidden"),
        "flood": TelegramRetryAfter(method=method, message="Too Many", retry_after=3),
        "failed": TimeoutError(),
    }
    for outcome, error in cases.items():
        before = _sent(outcome)
        await tell(_Bot(error), tg_id=42, text="x", lang=UiLang.RU)  # ty: ignore[invalid-argument-type]
        assert _sent(outcome) == before + 1, outcome


class _Session:
    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_: object) -> None: ...

    async def commit(self) -> None: ...


async def test_a_failed_notification_does_not_log_who_it_was_for(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The people it writes to are its audience; their ids stay out of the logs."""
    method = SendMessage(chat_id=424242, text="x")
    with caplog.at_level(logging.DEBUG, logger="students_cz"):
        await tell(
            _Bot(TelegramRetryAfter(method=method, message="Too Many", retry_after=3)),  # ty: ignore[invalid-argument-type]
            tg_id=424242,
            text="x",
            lang=UiLang.RU,
        )
        await tell(_Bot(TimeoutError()), tg_id=424242, text="x", lang=UiLang.RU)  # ty: ignore[invalid-argument-type]
        await tell(None, tg_id=424242, text="x", lang=UiLang.RU)

    assert caplog.records
    assert "424242" not in caplog.text


@pytest.mark.parametrize("short", ["x", "a" * 31])
def test_a_short_secret_refuses_to_start(short: str) -> None:
    from students_cz.core.config import Settings

    with pytest.raises(ValueError, match="OBSERVABILITY_METRICS_SECRET"):
        Settings(observability_metrics_secret=short)


def test_a_long_enough_secret_is_kept_and_blank_is_off() -> None:
    from students_cz.core.config import Settings

    kept = Settings(observability_metrics_secret=" " + "k" * 32 + "\n")
    assert kept.observability_metrics_secret.get_secret_value() == "k" * 32
    off = Settings(observability_metrics_secret="  ")
    assert off.observability_metrics_secret.get_secret_value() == ""
