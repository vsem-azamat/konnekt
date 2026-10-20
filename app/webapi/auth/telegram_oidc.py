"""Telegram OpenID Connect: the browser's way in (https://core.telegram.org/bots/telegram-login).

Authorization code flow with PKCE (S256). What makes it a door the console can
trust is where the proof comes from: the browser carries only a one-time `code`
that is useless without the verifier kept in its own cookie and the client
secret kept here, and the identity arrives as an `id_token` that Telegram signed
and this module checks against Telegram's published keys. Nothing a browser
could replay or forward names anybody.

The id_token's algorithm is chosen here, never by the token: a verifier that
reads `alg` from the header can be handed HS256 keyed with the public key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.exceptions import DomainError

ISSUER = "https://oauth.telegram.org"
AUTH_URL = f"{ISSUER}/auth"
TOKEN_URL = f"{ISSUER}/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"

# BotFather lets the owner pick among these; EdDSA and ES256K cannot carry the
# `profile` scope, and the numeric `id` the super-admin list is keyed by lives
# in `profile`.
_ALGORITHMS = ["RS256", "ES256"]
_SCOPE = "openid profile"
_LEEWAY_SECONDS = 30


class OidcError(DomainError):
    """The sign-in did not prove who is asking."""


@dataclass(frozen=True)
class AuthRequest:
    """One sign-in attempt: where to send the browser, and what to remember until it returns."""

    url: str
    state: str
    nonce: str
    verifier: str


def start(*, client_id: str, redirect_uri: str) -> AuthRequest:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return AuthRequest(url=f"{AUTH_URL}?{query}", state=state, nonce=nonce, verifier=verifier)


def verify_id_token(id_token: str, *, jwks: dict[str, Any], client_id: str, nonce: str) -> int:
    """The Telegram user id an id_token vouches for, or `OidcError`."""
    try:
        header = jwt.get_unverified_header(id_token)
        keys = {k.key_id: k for k in jwt.PyJWKSet.from_dict(jwks).keys}
        key = keys[header["kid"]]
        claims = jwt.decode(
            id_token,
            key=key.key,
            algorithms=_ALGORITHMS,
            audience=client_id,
            issuer=ISSUER,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as err:
        raise OidcError(f"id_token rejected: {type(err).__name__}") from err

    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("id_token rejected: nonce")
    user_id = claims.get("id")
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise OidcError("id_token rejected: no numeric id")
    return user_id


# Telegram rotates its keys rarely, and a token signed by one this copy has not
# seen simply fails once and is retried against a fresh copy.
_JWKS_TTL_SECONDS = 3600
_jwks_cache: tuple[float, dict[str, Any]] | None = None


def forget() -> None:
    """Drop the remembered key set; tests start from none."""
    global _jwks_cache  # noqa: PLW0603
    _jwks_cache = None


async def _jwks(http: httpx.AsyncClient, *, fresh: bool) -> dict[str, Any]:
    global _jwks_cache  # noqa: PLW0603
    if not fresh and _jwks_cache and time.monotonic() - _jwks_cache[0] < _JWKS_TTL_SECONDS:
        return _jwks_cache[1]
    try:
        resp = await http.get(JWKS_URL)
        resp.raise_for_status()
        keys = resp.json()
    except (httpx.HTTPError, ValueError) as err:
        raise OidcError(f"keys unavailable: {type(err).__name__}") from err
    _jwks_cache = (time.monotonic(), keys)
    return keys


async def complete(
    http: httpx.AsyncClient,
    *,
    code: str,
    verifier: str,
    nonce: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> int:
    """Trade the code for an id_token and return the Telegram user id it vouches for."""
    try:
        resp = await http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
            auth=(client_id, client_secret),
        )
        resp.raise_for_status()
        id_token = resp.json()["id_token"]
    except (httpx.HTTPError, ValueError, KeyError) as err:
        raise OidcError(f"token exchange failed: {type(err).__name__}") from err
    if not isinstance(id_token, str):
        raise OidcError("token exchange failed: no id_token")

    try:
        return verify_id_token(id_token, jwks=await _jwks(http, fresh=False), client_id=client_id, nonce=nonce)
    except OidcError:
        return verify_id_token(id_token, jwks=await _jwks(http, fresh=True), client_id=client_id, nonce=nonce)
