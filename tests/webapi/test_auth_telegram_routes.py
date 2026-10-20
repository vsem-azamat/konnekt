"""The browser's door: Telegram OpenID Connect, end to end against a fake Telegram.

The token endpoint and the key set are played by `httpx.MockTransport`; the
tokens are really signed. What is pinned: only the browser that started a
sign-in can finish it, a signed token for somebody outside the super-admin list
opens nothing, and every failure leaves the cookie jar without a session.
"""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from app.core.config import settings
from app.webapi.auth import telegram_oidc
from app.webapi.main import app
from app.webapi.routes import auth_telegram
from cryptography.hazmat.primitives.asymmetric import rsa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

CLIENT_ID = "123456789"
CLIENT_SECRET = "client-secret"  # noqa: S105
ADMIN_URL = "https://admin.example.test"
SUPER_ADMIN_ID = 268388996
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key: rsa.RSAPrivateKey = KEY, kid: str = "k1") -> dict:
    jwk = json.loads(jwt.get_algorithm_by_name("RS256").to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


class FakeTelegram:
    """Answers the token and key-set requests, and remembers what it was asked."""

    def __init__(self) -> None:
        self.user_id = SUPER_ADMIN_ID
        self.token_requests: list[httpx.Request] = []
        self.jwks_requests = 0
        self.token_status = 200
        self.nonce_override: str | None = None
        self.nonce: str | None = ""
        self.key = KEY
        self.kid = "k1"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == telegram_oidc.JWKS_URL:
            self.jwks_requests += 1
            return httpx.Response(200, json=_jwks(self.key, self.kid))
        if str(request.url) == telegram_oidc.TOKEN_URL:
            self.token_requests.append(request)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": telegram_oidc.ISSUER,
                "aud": CLIENT_ID,
                "sub": "opaque",
                "id": self.user_id,
                "nonce": self.nonce_override or self.nonce or None,
                "iat": now,
                "exp": now + 300,
            }
            claims = {k: v for k, v in claims.items() if v is not None}
            id_token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})
            return httpx.Response(200, json={"access_token": "x", "token_type": "Bearer", "id_token": id_token})
        return httpx.Response(404)


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def client_factory(db_session_maker: async_sessionmaker[AsyncSession], telegram: FakeTelegram):
    from app.webapi.deps import get_session, require_super_admin

    async def _override_session():
        async with db_session_maker() as s:
            yield s

    async def _override_http():
        async with httpx.AsyncClient(transport=httpx.MockTransport(telegram.handle)) as http:
            yield http

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[auth_telegram.get_oidc_http] = _override_http
    app.dependency_overrides.pop(require_super_admin, None)
    saved = (
        list(settings.admin.super_admins),
        settings.webapi.oidc_client_id,
        settings.webapi.oidc_client_secret,
        settings.webapi.admin_url,
        settings.webapi.session_cookie_secure,
    )
    settings.admin.super_admins = [SUPER_ADMIN_ID]
    settings.webapi.oidc_client_id = CLIENT_ID
    settings.webapi.oidc_client_secret = CLIENT_SECRET
    settings.webapi.admin_url = ADMIN_URL
    settings.webapi.session_cookie_secure = False
    telegram_oidc.forget()
    auth_telegram.forget()

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    yield make
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(auth_telegram.get_oidc_http, None)
    (
        settings.admin.super_admins,
        settings.webapi.oidc_client_id,
        settings.webapi.oidc_client_secret,
        settings.webapi.admin_url,
        settings.webapi.session_cookie_secure,
    ) = saved


async def _begin(client: httpx.AsyncClient, telegram: FakeTelegram) -> dict[str, str]:
    resp = await client.get("/api/auth/telegram/login")
    assert resp.status_code == 302, resp.text
    query = {k: v[0] for k, v in parse_qs(urlsplit(resp.headers["location"]).query).items()}
    telegram.nonce = query["nonce"]
    return query


async def test_the_login_route_sends_the_browser_to_telegram(client_factory, telegram) -> None:
    async with client_factory() as client:
        resp = await client.get("/api/auth/telegram/login")

    assert resp.status_code == 302
    location = urlsplit(resp.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == telegram_oidc.AUTH_URL
    query = parse_qs(location.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [f"{ADMIN_URL}/api/auth/telegram/callback"]
    flow = resp.headers["set-cookie"]
    assert "HttpOnly" in flow
    assert "Path=/;" in flow + ";"


async def test_a_completed_sign_in_opens_a_session_for_a_super_admin(client_factory, telegram) -> None:
    async with client_factory() as client:
        query = await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "the-code", "state": query["state"]})

        assert resp.status_code == 302
        assert resp.headers["location"] == f"{ADMIN_URL}/console"
        assert client.cookies.get(settings.webapi.session_cookie_name)
        me = await client.get("/api/auth/me")
        assert me.json()["user_id"] == SUPER_ADMIN_ID

    sent = telegram.token_requests[0]
    form = parse_qs(sent.content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["redirect_uri"] == [f"{ADMIN_URL}/api/auth/telegram/callback"]
    assert form["code_verifier"]
    assert "client_secret" not in form
    basic = base64.b64decode(sent.headers["authorization"].removeprefix("Basic ")).decode()
    assert basic == f"{CLIENT_ID}:{CLIENT_SECRET}"


async def test_a_finished_sign_in_cannot_be_replayed_from_the_same_browser(client_factory, telegram) -> None:
    """The callback clears the flow cookie; a server-side one-shot would need state we do not keep."""
    async with client_factory() as client:
        query = await _begin(client, telegram)
        done = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})
        assert "konnekt_oidc_flow=;" in done.headers["set-cookie"].replace('""', "")
        replay = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

    assert replay.headers["location"] == f"{ADMIN_URL}/login?error=failed"
    assert len(telegram.token_requests) == 1


async def test_a_signed_token_for_somebody_outside_the_list_opens_nothing(client_factory, telegram) -> None:
    telegram.user_id = 99999
    async with client_factory() as client:
        query = await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

        assert resp.headers["location"] == f"{ADMIN_URL}/login?error=not_admin"
        assert not client.cookies.get(settings.webapi.session_cookie_name)
        assert (await client.get("/api/auth/me")).status_code == 401


async def test_a_callback_from_a_browser_that_never_started_one_is_refused(client_factory, telegram) -> None:
    """Login CSRF: somebody's own valid state and code, delivered to the admin's browser."""
    async with client_factory() as attacker:
        query = await _begin(attacker, telegram)
    async with client_factory() as victim:
        resp = await victim.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

        assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"
        assert not victim.cookies.get(settings.webapi.session_cookie_name)
    assert telegram.token_requests == []


async def test_a_state_that_is_not_the_one_issued_is_refused(client_factory, telegram) -> None:
    async with client_factory() as client:
        await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "forged"})

    assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"
    assert telegram.token_requests == []


async def test_a_token_minted_for_another_login_is_refused(client_factory, telegram) -> None:
    telegram.nonce_override = "someone-elses-nonce"
    async with client_factory() as client:
        query = await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

        assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"
        assert not client.cookies.get(settings.webapi.session_cookie_name)


async def test_telegram_refusing_the_code_ends_the_sign_in(client_factory, telegram) -> None:
    telegram.token_status = 400
    async with client_factory() as client:
        query = await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

        assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"


async def test_the_user_declining_at_telegram_ends_the_sign_in(client_factory, telegram) -> None:
    async with client_factory() as client:
        query = await _begin(client, telegram)
        resp = await client.get(
            "/api/auth/telegram/callback", params={"error": "access_denied", "state": query["state"]}
        )

        assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"
    assert telegram.token_requests == []


async def test_the_keys_are_fetched_once_and_remembered(client_factory, telegram) -> None:
    async with client_factory() as client:
        for _ in range(2):
            query = await _begin(client, telegram)
            await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

    assert telegram.jwks_requests == 1


async def test_the_door_is_absent_until_it_is_configured(client_factory, telegram) -> None:
    settings.webapi.oidc_client_secret = ""
    async with client_factory() as client:
        login = await client.get("/api/auth/telegram/login")
        callback = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})

    assert login.status_code == 404
    assert callback.status_code == 404


async def test_a_state_that_is_not_ascii_is_refused_not_a_server_error(client_factory, telegram) -> None:
    async with client_factory() as client:
        await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "é"})

    assert resp.status_code == 302
    assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"


async def test_a_flow_cookie_without_a_nonce_is_refused(client_factory, telegram) -> None:
    async with client_factory() as client:
        client.cookies.set("konnekt_oidc_flow", "s..v")
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})

    assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"
    assert telegram.token_requests == []


async def test_a_token_without_a_nonce_still_signs_in(client_factory, telegram) -> None:
    async with client_factory() as client:
        query = await _begin(client, telegram)
        telegram.nonce = None
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

    assert resp.headers["location"] == f"{ADMIN_URL}/console"


async def test_the_flow_cookie_cannot_be_planted_by_a_sibling_host(client_factory) -> None:
    """`__Host-` means Secure, no Domain, Path=/: a sibling subdomain cannot set one."""
    settings.webapi.session_cookie_secure = True
    async with client_factory() as client:
        resp = await client.get("/api/auth/telegram/login")

    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-konnekt_oidc_flow=")
    for attribute in ("Secure", "HttpOnly", "Path=/;", "SameSite=lax", "Max-Age=600"):
        assert attribute in cookie + ";"
    assert "Domain" not in cookie


async def test_a_rotated_key_is_fetched_once_the_remembered_set_is_old_enough(
    client_factory, telegram, monkeypatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(telegram_oidc, "_clock", lambda: clock[0])
    async with client_factory() as client:
        query = await _begin(client, telegram)
        await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})
        assert telegram.jwks_requests == 1

        telegram.key, telegram.kid = rsa.generate_private_key(public_exponent=65537, key_size=2048), "k2"
        clock[0] += telegram_oidc.REFETCH_AFTER_SECONDS + 1
        query = await _begin(client, telegram)
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})

    assert resp.headers["location"] == f"{ADMIN_URL}/console"
    assert telegram.jwks_requests == 2


async def test_unknown_keys_do_not_make_us_hammer_telegram(client_factory, telegram, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(telegram_oidc, "_clock", lambda: clock[0])
    async with client_factory() as client:
        query = await _begin(client, telegram)
        await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})
        telegram.kid = "unknown"
        for _ in range(3):
            query = await _begin(client, telegram)
            resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": query["state"]})
            assert resp.headers["location"] == f"{ADMIN_URL}/login?error=failed"

    assert telegram.jwks_requests == 1


async def test_callbacks_are_limited_per_address(client_factory, telegram) -> None:
    async with client_factory() as client:
        answers = [
            (await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})).status_code
            for _ in range(auth_telegram.CALLBACKS_PER_MINUTE + 1)
        ]

    assert answers[:-1] == [302] * auth_telegram.CALLBACKS_PER_MINUTE
    assert answers[-1] == 429


def _from(address: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(address, 1234)), base_url="http://test")


async def test_an_ipv6_network_shares_one_allowance(client_factory) -> None:
    """A /64 is one subscriber's to hand out; counting addresses would give them 2**64 allowances."""
    answers = []
    for index in range(auth_telegram.CALLBACKS_PER_MINUTE + 1):
        async with _from(f"2001:db8:1:2::{index + 1:x}") as client:
            answers.append(
                (await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})).status_code
            )

    assert answers[-1] == 429


async def test_another_ipv6_network_has_its_own_allowance(client_factory) -> None:
    for index in range(auth_telegram.CALLBACKS_PER_MINUTE):
        async with _from(f"2001:db8:1:2::{index + 1:x}") as client:
            await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})
    async with _from("2001:db8:1:3::1") as client:
        resp = await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})

    assert resp.status_code == 302


async def test_a_full_table_forgets_the_oldest_caller_and_keeps_the_rest(client_factory, monkeypatch) -> None:
    """Clearing it all would hand every address that was at its limit a fresh one."""
    monkeypatch.setattr(auth_telegram, "_REMEMBERED", 3)
    for address in ("192.0.2.1", "192.0.2.2", "192.0.2.3", "192.0.2.4"):
        async with _from(address) as client:
            await client.get("/api/auth/telegram/callback", params={"code": "c", "state": "s"})

    assert set(auth_telegram._callbacks) == {"192.0.2.2", "192.0.2.3", "192.0.2.4"}
