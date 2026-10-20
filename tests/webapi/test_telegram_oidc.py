"""Telegram OpenID Connect: what an id_token must prove before it opens a session.

The token is the only thing in the flow that names a person, so these tests
forge it every way a caller could: another issuer, another audience, another
login's nonce, an expired one, an unsigned one, a key Telegram never published,
and the HS256-with-the-public-key trick that fools verifiers choosing the
algorithm from the token's own header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from app.webapi.auth import telegram_oidc
from app.webapi.auth.telegram_oidc import ISSUER, OidcError, start, verify_id_token
from cryptography.hazmat.primitives.asymmetric import ec, rsa

CLIENT_ID = "123456789"
REDIRECT = "https://admin.example.test/api/auth/telegram/callback"
NONCE = "nonce-of-this-login"
USER_ID = 268388996


def _rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return _rsa_key()


def _jwks(private_key, *, kid: str = "k1", alg: str = "RS256") -> dict:
    algorithm = jwt.get_algorithm_by_name(alg)
    jwk = json.loads(algorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": alg})
    return {"keys": [jwk]}


def _token(private_key, *, kid: str = "k1", alg: str = "RS256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "opaque-subject",
        "id": USER_ID,
        "nonce": NONCE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm=alg, headers={"kid": kid})


def _verify(token: str, jwks: dict) -> int:
    return verify_id_token(token, jwks=jwks, client_id=CLIENT_ID, nonce=NONCE)


def test_a_genuine_token_names_the_telegram_user(key) -> None:
    assert _verify(_token(key), _jwks(key)) == USER_ID


def test_an_ec_key_telegram_may_be_switched_to_is_accepted() -> None:
    ec_key = ec.generate_private_key(ec.SECP256R1())
    token = _token(ec_key, alg="ES256")
    assert _verify(token, _jwks(ec_key, alg="ES256")) == USER_ID


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example"},
        {"aud": "987654321"},
        {"nonce": "another-login"},
        {"nonce": None},
        {"exp": int(time.time()) - 600},
        {"id": None},
        {"id": "268388996"},
        {"id": True},
    ],
    ids=["issuer", "audience", "nonce", "no-nonce", "expired", "no-id", "id-as-string", "id-as-bool"],
)
def test_a_token_that_proves_the_wrong_thing_is_refused(key, overrides) -> None:
    with pytest.raises(OidcError):
        _verify(_token(key, **overrides), _jwks(key))


def test_a_token_signed_by_a_key_telegram_never_published_is_refused(key) -> None:
    with pytest.raises(OidcError):
        _verify(_token(_rsa_key()), _jwks(key))


def test_an_unknown_key_id_is_refused(key) -> None:
    with pytest.raises(OidcError):
        _verify(_token(key, kid="other"), _jwks(key))


def test_an_unsigned_token_is_refused(key) -> None:
    body = {"iss": ISSUER, "aud": CLIENT_ID, "id": USER_ID, "nonce": NONCE, "exp": int(time.time()) + 300}

    def b64(part: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    unsigned = f"{b64({'alg': 'none', 'kid': 'k1'})}.{b64(body)}."
    with pytest.raises(OidcError):
        _verify(unsigned, _jwks(key))


def test_hs256_keyed_with_the_public_key_is_refused(key) -> None:
    from cryptography.hazmat.primitives import serialization

    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "id": USER_ID, "nonce": NONCE, "exp": int(time.time()) + 300}
    signing_input = f"{header}.{b64(json.dumps(claims).encode())}"
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    with pytest.raises(OidcError):
        _verify(f"{signing_input}.{b64(signature)}", _jwks(key))


def test_garbage_is_refused(key) -> None:
    with pytest.raises(OidcError):
        _verify("not.a.jwt", _jwks(key))


def test_start_builds_an_s256_pkce_request_with_fresh_secrets() -> None:
    first = start(client_id=CLIENT_ID, redirect_uri=REDIRECT)
    second = start(client_id=CLIENT_ID, redirect_uri=REDIRECT)

    url = urlsplit(first.url)
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == telegram_oidc.AUTH_URL
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT
    assert query["scope"].split() == ["openid", "profile"]
    assert query["state"] == first.state
    assert query["nonce"] == first.nonce
    assert query["code_challenge_method"] == "S256"
    expected = base64.urlsafe_b64encode(hashlib.sha256(first.verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == expected
    assert len(first.verifier) >= 43
    assert {first.state, first.nonce, first.verifier}.isdisjoint({second.state, second.nonce, second.verifier})
