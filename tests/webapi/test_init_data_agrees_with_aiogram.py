"""Our initData check and aiogram's agree on every payload.

The catalog verifies the same bot's initData with aiogram's helper and the
console and the join check with our own; a change in Telegram's signing that
one of them follows and the other does not would split the Mini App in two.
The payloads here are signed the way Telegram signs them, and both checks
must give the same answer for each.
"""

from __future__ import annotations

import pytest
from aiogram.utils.web_app import check_webapp_signature
from app.webapi.auth.telegram_webapp import InitDataError, verify_init_data

from tests.webapi.test_auth_routes import _init_data

TOKEN = "123456:ABC-DEF1234567890"  # noqa: S105 — test fixture


def _ours(raw: str) -> bool:
    try:
        verify_init_data(raw, bot_token=TOKEN)
    except InitDataError:
        return False
    return True


@pytest.mark.parametrize("signature", ["Xf2pQ", None])
def test_a_genuine_payload_passes_both(signature: str | None) -> None:
    raw = _init_data(user_id=42, token=TOKEN, signature=signature)

    assert (_ours(raw), check_webapp_signature(TOKEN, raw)) == (True, True)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda raw: raw.replace("42", "43", 1),
        lambda raw: raw.replace("signature=Xf2pQ", "signature=other"),
        lambda raw: raw + "&extra=1",
    ],
)
def test_a_tampered_payload_fails_both(tamper) -> None:
    raw = tamper(_init_data(user_id=42, token=TOKEN))

    assert (_ours(raw), check_webapp_signature(TOKEN, raw)) == (False, False)


def test_another_bots_signature_fails_both() -> None:
    raw = _init_data(user_id=42, token="999:another-bots-token")

    assert (_ours(raw), check_webapp_signature(TOKEN, raw)) == (False, False)
