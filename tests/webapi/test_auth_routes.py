"""The console has one door: a signed Mini App payload.

The Login Widget and the magic link are gone, so what is pinned here is that
nothing else opens it. A forged signature, a stale one, and a real signature
from somebody who is not a super administrator all fail — and they fail
differently in the log and identically to the caller.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from app.core.config import settings
from app.webapi.main import app
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "test:bot:token"  # noqa: S105
SUPER_ADMIN_ID = 268388996


def _init_data(*, user_id: int, token: str = BOT_TOKEN, age_seconds: int = 0, signature: str | None = "Xf2pQ") -> str:
    """Build an initData string the way Telegram would.

    Note the secret: HMAC over the literal b"WebAppData", not sha256 of the
    token. The Login Widget used the other one, and signing this payload that
    way is exactly the forgery the endpoint has to refuse.

    And note `signature`, present by default because Telegram has sent it since
    Bot API 7.10 — there is no current client that omits it. Every test here
    once built the payload without it, so the suite stayed green through eight
    days in which the endpoint refused every genuine sign-in.
    """
    issued = int(datetime.datetime.now(tz=datetime.UTC).timestamp()) - age_seconds
    fields = {
        "auth_date": str(issued),
        "query_id": "AAF",
        "user": json.dumps({"id": user_id, "first_name": "A"}, separators=(",", ":")),
    }
    if signature is not None:
        fields["signature"] = signature
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession]):
    from app.webapi.deps import get_session, require_super_admin

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    orig_admins = list(settings.admin.super_admins)
    orig_token = settings.telegram.token
    orig_secure = settings.webapi.session_cookie_secure
    settings.admin.super_admins = [SUPER_ADMIN_ID]
    settings.telegram.token = BOT_TOKEN
    settings.webapi.session_cookie_secure = False

    app.dependency_overrides.pop(require_super_admin, None)
    transport = ASGITransport(app=app)

    def make() -> AsyncClient:
        return AsyncClient(transport=transport, base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)
    settings.admin.super_admins = orig_admins
    settings.telegram.token = orig_token
    settings.webapi.session_cookie_secure = orig_secure


async def test_me_unauthenticated_returns_401(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_a_signed_payload_opens_a_session(client_factory) -> None:
    async with client_factory() as client:
        resp = await client.post("/api/auth/webapp", json={"init_data": _init_data(user_id=SUPER_ADMIN_ID)})
        assert resp.status_code == 200, resp.text
        assert resp.cookies.get(settings.webapi.session_cookie_name)

        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user_id"] == SUPER_ADMIN_ID


async def test_a_payload_from_a_client_that_predates_the_signature_field_still_opens_a_session(
    client_factory,
) -> None:
    """The field is not required — only covered by the digest when it is there."""
    async with client_factory() as client:
        resp = await client.post(
            "/api/auth/webapp",
            json={"init_data": _init_data(user_id=SUPER_ADMIN_ID, signature=None)},
        )

    assert resp.status_code == 200, resp.text


async def test_a_refused_signature_and_a_refused_admin_are_told_apart(client_factory) -> None:
    """401 is "Telegram did not sign this"; 403 is "signed, but not for you".

    The console shows one screen for both, and it reads as the second. That is
    how a verification bug spent eight days looking like a missing entry in the
    super-admin list.
    """
    async with client_factory() as client:
        unsigned = await client.post("/api/auth/webapp", json={"init_data": "auth_date=1&hash=deadbeef"})
        stranger = await client.post("/api/auth/webapp", json={"init_data": _init_data(user_id=99999)})

    assert unsigned.status_code == 401
    assert stranger.status_code == 403


async def test_a_payload_signed_with_another_token_is_refused(client_factory) -> None:
    """Which is what a Mini App belonging to a different bot would send."""
    forged = _init_data(user_id=SUPER_ADMIN_ID, token="someone:elses:token")  # noqa: S106

    async with client_factory() as client:
        resp = await client.post("/api/auth/webapp", json={"init_data": forged})

    assert resp.status_code == 401
    assert not resp.cookies.get(settings.webapi.session_cookie_name)


async def test_a_stale_payload_is_refused(client_factory) -> None:
    """A signature stays valid forever; replaying one must not."""
    async with client_factory() as client:
        resp = await client.post(
            "/api/auth/webapp",
            json={"init_data": _init_data(user_id=SUPER_ADMIN_ID, age_seconds=90_000)},
        )

    assert resp.status_code == 401


async def test_a_genuine_stranger_is_refused(client_factory) -> None:
    """Telegram vouches for who they are, not for what they may do."""
    async with client_factory() as client:
        resp = await client.post("/api/auth/webapp", json={"init_data": _init_data(user_id=99999)})

    assert resp.status_code == 403
    assert not resp.cookies.get(settings.webapi.session_cookie_name)


async def test_an_empty_payload_is_refused(client_factory) -> None:
    """The case a browser outside Telegram would produce."""
    async with client_factory() as client:
        resp = await client.post("/api/auth/webapp", json={"init_data": ""})

    assert resp.status_code == 401


async def test_the_old_doors_are_gone(client_factory) -> None:
    """Deleting a login route is only true if nothing still answers on it."""
    async with client_factory() as client:
        widget = await client.post("/api/auth/login", json={"id": SUPER_ADMIN_ID, "auth_date": 0, "hash": "x"})
        magic = await client.post("/api/auth/magic-link", json={"token": "x"})

    assert widget.status_code == 404
    assert magic.status_code == 404


def test_routes_without_a_client_are_gone() -> None:
    """The Svelte console's readers left with it; an unread endpoint is attack
    surface and upkeep with nothing on the other side."""
    paths = app.openapi()["paths"]

    assert "/api/chats/graph" not in paths
    assert "/api/chats/{chat_id}/avatar" not in paths
    assert "get" not in paths.get("/api/users/{user_id}", {})


async def test_the_database_keeps_a_digest_not_the_cookie(client_factory, db_session_maker) -> None:
    """A copy of the table, a backup or a careless query would otherwise be every live console session."""
    import hashlib

    from app.db.models import AdminSession
    from sqlalchemy import select

    async with client_factory() as client:
        resp = await client.post("/api/auth/webapp", json={"init_data": _init_data(user_id=SUPER_ADMIN_ID)})
        token = resp.cookies.get(settings.webapi.session_cookie_name)
        me = await client.get("/api/auth/me")

    async with db_session_maker() as session:
        stored = (await session.scalars(select(AdminSession.session_id))).all()
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert me.status_code == 200


async def test_signing_out_ends_the_session_here(client_factory, db_session_maker) -> None:
    """A 30-day cookie could not be ended from the device holding it."""
    from app.db.models import AdminSession
    from sqlalchemy import select

    async with client_factory() as client:
        await client.post("/api/auth/webapp", json={"init_data": _init_data(user_id=SUPER_ADMIN_ID)})
        out = await client.post("/api/auth/logout")
        after = await client.get("/api/auth/me")

    assert out.status_code == 204
    assert "max-age=0" in out.headers.get("set-cookie", "").lower()
    assert after.status_code == 401
    async with db_session_maker() as session:
        assert (await session.scalars(select(AdminSession))).all() == []


async def test_signing_out_without_a_session_is_harmless(client_factory) -> None:
    async with client_factory() as client:
        out = await client.post("/api/auth/logout")

    assert out.status_code == 204


def test_samesite_none_is_refused() -> None:
    """Lax is the only defence the console's mutations have against cross-site requests."""
    import pytest
    from app.core.config import WebApiSettings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WebApiSettings.model_validate({"session_cookie_samesite": "none"})


def test_samesite_is_read_whatever_its_case() -> None:
    """`Lax` in an env file must not stop every process at import."""
    from app.core.config import WebApiSettings

    assert WebApiSettings.model_validate({"session_cookie_samesite": "Lax"}).session_cookie_samesite == "lax"


@pytest.mark.parametrize(
    ("host", "recorded"),
    [("203.0.113.9", "203.0.113.9"), ("2001:db8::1", "2001:db8::1"), ("x" * 200, None), ("fe80::1%" + "e" * 100, None)],
)
def test_only_an_address_is_recorded(host: str, recorded: str | None) -> None:
    """It arrives through forwarded headers; the column is 64 characters and the console shows it."""
    from types import SimpleNamespace

    from app.webapi.routes.auth import _address

    assert _address(SimpleNamespace(client=SimpleNamespace(host=host))) == recorded  # ty: ignore[invalid-argument-type]
