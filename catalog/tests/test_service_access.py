"""The console's server calling on an operator's behalf.

In a browser the console has no initData, so supervisor's webapi asks here for
the operator it signed in, with a token both containers are started with. See
docs/architecture.md, «The operator reads the catalog and runs the partner
cards».
"""

import logging

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from students_cz.core.config import Settings, get_settings
from students_cz.db.models import User

from .conftest import app_for, auth_header

pytestmark = pytest.mark.asyncio

OPERATOR = 97101
STRANGER = 97102
TOKEN = "s3rv1ce-t0ken-for-tests-only-and-long-enough"


def _client(session: AsyncSession, token: str = TOKEN) -> AsyncClient:
    app = app_for(session)
    configured = Settings(
        _env_file=None, admin_tg_ids=[OPERATOR], service_token=SecretStr(token)
    )
    app.dependency_overrides[get_settings] = lambda: configured
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _service(
    operator: int | str = OPERATOR, token: str = TOKEN, **extra: str
) -> dict[str, str]:
    return {"X-Catalog-Service": token, "X-Catalog-Operator": str(operator), **extra}


ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/catalog"),
    ("GET", "/api/v1/admin/partners"),
    ("POST", "/api/v1/admin/placements"),
    ("PATCH", "/api/v1/admin/placements/1"),
    ("GET", "/api/v1/admin/profiles/1"),
    ("POST", "/api/v1/admin/profiles/1/review"),
    ("POST", "/api/v1/admin/profiles/1/hide"),
    ("POST", "/api/v1/admin/profiles/1/restore"),
    ("GET", "/api/v1/taxonomy/institutions"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
async def test_the_console_server_asks_for_an_operator(
    session: AsyncSession, method: str, path: str
) -> None:
    async with _client(session) as http:
        response = await http.request(
            method, path, headers=_service(), json={"is_active": False}
        )

    # Past the door: whatever the route says next (a missing profile is a 404,
    # an empty card a 422) is its own answer, not a refusal.
    assert response.status_code not in (401, 403)


async def test_the_catalog_reads_as_the_operator_would(session: AsyncSession) -> None:
    async with _client(session) as http:
        response = await http.get("/api/v1/admin/catalog", headers=_service())

    assert response.status_code == 200
    assert "counts" in response.json()


@pytest.mark.parametrize(
    "headers",
    [
        _service(token="not-the-token"),
        _service(token=""),
        {"X-Catalog-Service": TOKEN},
        _service(operator="me"),
        _service(operator="-5"),
        _service(operator="0"),
        _service(operator="9" * 21),
        _service(operator="9" * 5000),
        _service(operator="٤٢"),
        _service(operator="４２"),
    ],
    ids=[
        "wrong token",
        "empty token",
        "no operator",
        "not a number",
        "negative",
        "zero",
        "too long",
        "far too long",
        "arabic digits",
        "fullwidth digits",
    ],
)
async def test_a_wrong_or_partial_service_call_is_refused(
    session: AsyncSession, headers: dict[str, str]
) -> None:
    # As bytes, so a header can carry what a browser could: UTF-8, not ASCII.
    raw = {name.encode(): value.encode() for name, value in headers.items()}
    async with _client(session) as http:
        response = await http.get("/api/v1/admin/catalog", headers=raw)

    assert response.status_code == 401


async def test_without_a_token_configured_nothing_is_a_service_call(
    session: AsyncSession,
) -> None:
    """Unset is off: an empty header must not match an empty setting."""
    async with _client(session, token="") as http:
        empty = await http.get("/api/v1/admin/catalog", headers=_service(token=""))
        anything = await http.get("/api/v1/admin/catalog", headers=_service())

    assert empty.status_code == 401
    assert anything.status_code == 401


async def test_the_operator_must_still_be_one(session: AsyncSession) -> None:
    """Who is an operator stays the catalog's rule, whoever asks."""
    async with _client(session) as http:
        response = await http.get(
            "/api/v1/admin/catalog", headers=_service(operator=STRANGER)
        )

    assert response.status_code == 403


async def test_a_wrong_token_does_not_fall_back_to_init_data(
    session: AsyncSession,
) -> None:
    async with _client(session) as http:
        response = await http.get(
            "/api/v1/admin/catalog",
            headers={**auth_header(OPERATOR), **_service(token="not-the-token")},
        )

    assert response.status_code == 401


async def test_the_token_decides_whoever_the_init_data_names(
    session: AsyncSession,
) -> None:
    """A stranger's initData beside a valid service call is not looked at."""
    async with _client(session) as http:
        response = await http.get(
            "/api/v1/admin/catalog",
            headers={**auth_header(STRANGER), **_service()},
        )

    assert response.status_code == 200


async def test_init_data_still_opens_the_console(session: AsyncSession) -> None:
    async with _client(session) as http:
        admin = await http.get("/api/v1/admin/catalog", headers=auth_header(OPERATOR))
        stranger = await http.get("/api/v1/admin/catalog", headers=auth_header(STRANGER))
        anybody = await http.get(
            "/api/v1/taxonomy/institutions", headers=auth_header(STRANGER)
        )

    assert admin.status_code == 200
    assert stranger.status_code == 403
    assert anybody.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/helper"),
        ("GET", "/api/v1/placements?slot=life"),
        ("GET", "/api/v1/taxonomy/service-types"),
    ],
)
async def test_the_token_opens_nothing_but_the_console(
    session: AsyncSession, method: str, path: str
) -> None:
    """It names an operator, never a person: nobody's own screens open with it."""
    async with _client(session) as http:
        response = await http.request(method, path, headers=_service())

    assert response.status_code == 401


async def test_a_service_call_registers_nobody(session: AsyncSession) -> None:
    async with _client(session) as http:
        await http.get("/api/v1/admin/catalog", headers=_service())
        await http.get("/api/v1/taxonomy/institutions", headers=_service())

    count = await session.scalar(
        select(func.count()).select_from(User).where(User.tg_id == OPERATOR)
    )
    assert count == 0


async def test_the_console_names_its_language(session: AsyncSession) -> None:
    async with _client(session) as http:
        english = await http.get(
            "/api/v1/taxonomy/institutions", headers=_service(**{"X-Catalog-Lang": "en"})
        )
        unnamed = await http.get("/api/v1/taxonomy/institutions", headers=_service())
        unknown = await http.get(
            "/api/v1/taxonomy/institutions", headers=_service(**{"X-Catalog-Lang": "xx"})
        )

    def name(response, code: str) -> str:
        return next(row["name"] for row in response.json() if row["code"] == code)

    assert name(english, "cvut") == "Czech Technical University in Prague"
    assert name(unnamed, "cvut") == "Чешский технический университет в Праге"
    assert unknown.status_code == 422


async def test_a_refusal_never_logs_the_token(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    attempt = "a-guess-that-is-close-to-the-real-one"
    with caplog.at_level(logging.INFO, logger="students_cz.auth"):
        async with _client(session) as http:
            await http.get("/api/v1/admin/catalog", headers=_service(token=attempt))

    assert "service_call_rejected" in caplog.text
    assert attempt not in caplog.text
    assert TOKEN not in caplog.text


async def test_a_service_call_is_written_down(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Who was acted as, and what was asked: the token is not in it."""
    with caplog.at_level(logging.INFO, logger="students_cz.auth"):
        async with _client(session) as http:
            await http.post("/api/v1/admin/profiles/1/hide", headers=_service())

    (record,) = [r for r in caplog.records if r.getMessage().startswith("service_call ")]
    assert str(OPERATOR) in record.getMessage()
    assert "POST /api/v1/admin/profiles/1/hide" in record.getMessage()
    assert TOKEN not in caplog.text


async def test_the_token_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", TOKEN)
    assert Settings(_env_file=None).service_token.get_secret_value() == TOKEN
    monkeypatch.delenv("SERVICE_TOKEN")
    assert Settings(_env_file=None).service_token.get_secret_value() == ""
    assert TOKEN not in repr(Settings(_env_file=None, service_token=SecretStr(TOKEN)))


@pytest.mark.parametrize("value", ["   ", "\t\n", ""])
async def test_a_blank_token_is_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", value)
    assert Settings(_env_file=None).service_token.get_secret_value() == ""


async def test_a_token_is_read_without_the_spaces_around_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", f"  {TOKEN}\n")
    assert Settings(_env_file=None).service_token.get_secret_value() == TOKEN


@pytest.mark.parametrize("value", ["short", "x" * 31])
async def test_a_weak_token_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SERVICE_TOKEN", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
